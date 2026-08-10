from __future__ import annotations

import uuid

from sqlalchemy import String, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from backend.db import Base


class CodeEmbedding(Base):
    __tablename__ = "code_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    symbol_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("code_symbols.id", ondelete="CASCADE"), nullable=False
    )
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    symbol_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    symbol_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    embedding = mapped_column(Vector(2048), nullable=False)

    symbol: Mapped["CodeSymbol"] = relationship(back_populates="embeddings")  # noqa: F821
    repository: Mapped["Repository"] = relationship(back_populates="embeddings")  # noqa: F821

    # No ANN index — pgvector caps ivfflat/hnsw at 2000 dims, and
    # nemotron-3-embed-1b produces 2048-dim vectors. Exact cosine
    # search is fast enough for typical codebase sizes (<100k symbols).
