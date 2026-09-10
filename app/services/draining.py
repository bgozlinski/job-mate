"""Moving staged postings into the knowledge base (FR-7).

The asyncio half of the seam. A spider has already written rows to
staging_postings with a synchronous driver and gone away; this walks those
rows through the ordinary FR-1 ingestion, so nothing about chunking,
embedding or deduplication is decided a second time here.

**Why this is not one transaction.** ingest_document commits for itself, so
the document and the staged row's new state land in two transactions and a
crash can fall between them. That is safe because a re-run is free of
consequence: the row is still pending, the drain reaches it again, and
ingest_document finds the document by content_hash and answers created=False
before it spends anything on embeddings. The row is then marked ingested. The
cost of the crash is one SELECT, and the alternative -- prying the commit out
of the FR-1 path so that a much later feature can share its transaction --
would put the risk on the path that already works.

**A duplicate is not a failure.** A staged posting whose text is already in
documents was collected correctly and needs no document of its own; it is
counted apart from a real failure so that a source republishing unchanged
listings does not read as a broken source.

**Concurrency.** The claim uses FOR UPDATE SKIP LOCKED, which keeps two
drains running at the same instant off each other's rows, but the lock ends
with the claim transaction rather than covering the ingestion. Correctness
under overlap therefore rests on the re-run being idempotent, not on the
lock, and the intended arrangement is a single scheduled drain. Making
overlap efficient rather than merely safe wants a claimed state, which is a
migration, and nothing needs it yet.
"""

import logging
import uuid
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.staging import StagingPosting, StagingState
from app.services.embeddings import EmbeddingModel
from app.services.ingestion import SourceDocument, ingest_document
from app.services.requirements import SkillExtractor

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 50
MAX_ERROR_LENGTH = 500


@dataclass(frozen=True)
class DrainReport:
    """What one pass of the drain did.

    duplicates counts postings that were already in the knowledge base, and
    they are also ingested as far as the staging row is concerned -- the
    split exists so that a source can be judged on it.
    """

    ingested: int = 0
    duplicates: int = 0
    failed: int = 0

    @property
    def handled(self) -> int:
        """How many staged rows stopped being pending."""
        return self.ingested + self.duplicates + self.failed


@dataclass(frozen=True)
class _Claimed:
    """A staged row copied out before any commit can expire it."""

    id: uuid.UUID
    source_id: uuid.UUID
    external_id: str | None
    url: str
    title: str | None
    content: str


async def _claim(session: AsyncSession, limit: int) -> list[_Claimed]:
    """Take the oldest pending rows, skipping any another drain holds."""
    rows = await session.scalars(
        select(StagingPosting)
        .where(StagingPosting.state == StagingState.PENDING)
        .order_by(StagingPosting.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    claimed = [
        _Claimed(
            id=row.id,
            source_id=row.source_id,
            external_id=row.external_id,
            url=row.url,
            title=row.title,
            content=row.content,
        )
        for row in rows
    ]
    await session.commit()

    return claimed


async def _mark(
    session: AsyncSession,
    posting_id: uuid.UUID,
    state: StagingState,
    error: str | None = None,
) -> None:
    """Record what became of one staged row.

    Addressed by id rather than through the ORM object, which a rollback in
    the middle of a failed ingestion may have expired.
    """
    await session.execute(
        update(StagingPosting)
        .where(StagingPosting.id == posting_id)
        .values(state=state, error=error)
    )
    await session.commit()


async def drain_staging(
    session: AsyncSession,
    model: EmbeddingModel,
    cache: Redis,
    extractor: SkillExtractor | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> DrainReport:
    """Ingest every pending staged posting, one at a time.

    One posting failing is not the batch failing: FR-7 wants a source that
    has gone wrong to stop without taking the schedule with it, and that is
    only true if the row records its own reason and the pass carries on. The
    reason is stored on the row, which is where someone will look, and logged
    with a traceback, which is where the cause is.
    """
    claimed = await _claim(session, batch_size)
    ingested = duplicates = failed = 0

    for posting in claimed:
        try:
            result = await ingest_document(
                session,
                SourceDocument(
                    content=posting.content,
                    title=posting.title,
                    source_url=posting.url,
                    source_id=posting.source_id,
                    external_id=posting.external_id,
                ),
                model,
                cache,
                extractor,
            )
        except Exception as exc:
            # Anything at all: an empty posting, a provider that is down, a
            # constraint nobody foresaw. The row keeps the reason and the
            # pass moves on to the next posting.
            await session.rollback()
            logger.exception("Could not ingest staged posting %s", posting.id)
            await _mark(
                session,
                posting.id,
                StagingState.FAILED,
                f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH],
            )
            failed += 1
        else:
            await _mark(session, posting.id, StagingState.INGESTED)

            if result.created:
                ingested += 1
            else:
                duplicates += 1

    return DrainReport(ingested=ingested, duplicates=duplicates, failed=failed)
