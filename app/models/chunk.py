"""The chunks table: the fragments retrieval actually searches over."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.document import Document

EMBEDDING_DIMENSIONS = 1536
"""Fixed by the embedding model. Changing models means a re-indexing
migration (FR-6), not an in-place edit: the column width is part of the
schema and old vectors are meaningless under a new model."""


class Chunk(Base):
    """One fragment of a document, with the vector it was embedded into.

    chunk_index numbers the fragments within their document from 0, so the
    original order can be reconstructed. The unique constraint over
    (document_id, chunk_index) is what stops a repeated ingestion of the
    same document from writing every fragment twice.

    embedding is NOT NULL on purpose: a chunk without a vector is invisible
    to retrieval, so it would be silent data loss rather than a state worth
    representing. Chunks and their embeddings are written in one
    transaction; the Redis cache in front of the embeddings API (NFR-2a) is
    what keeps that affordable on re-ingestion.
    """

    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_index"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer())
    content: Mapped[str] = mapped_column(Text())
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    document: Mapped[Document] = relationship(back_populates="chunks")
