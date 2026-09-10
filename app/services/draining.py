"""Moving staged postings into the knowledge base (FR-7)."""

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
    """What one pass of the drain did."""

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
    """Record what became of one staged row."""
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
    """Ingest every pending staged posting, one at a time."""
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
