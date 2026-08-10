from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import String, DateTime, Enum, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base


class RepoStatus(str, PyEnum):
    pending = "pending"
    cloning = "cloning"
    indexing = "indexing"
    ready = "ready"
    error = "error"


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    github_url: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(100), default="main")
    status: Mapped[RepoStatus] = mapped_column(
        Enum(RepoStatus), default=RepoStatus.pending
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    files: Mapped[list["File"]] = relationship(  # noqa: F821
        back_populates="repository", cascade="all, delete-orphan"
    )
    symbols: Mapped[list["CodeSymbol"]] = relationship(  # noqa: F821
        back_populates="repository", cascade="all, delete-orphan"
    )
    embeddings: Mapped[list["CodeEmbedding"]] = relationship(  # noqa: F821
        back_populates="repository", cascade="all, delete-orphan"
    )
    chat_sessions: Mapped[list["ChatSession"]] = relationship(  # noqa: F821
        back_populates="repository", cascade="all, delete-orphan"
    )
