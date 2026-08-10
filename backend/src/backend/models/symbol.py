from __future__ import annotations

import uuid

from sqlalchemy import String, Integer, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base


class CodeSymbol(Base):
    __tablename__ = "code_symbols"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)  # function, class, method, module
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    docstring: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("code_symbols.id", ondelete="CASCADE"), nullable=True
    )

    file: Mapped["File"] = relationship(back_populates="symbols")  # noqa: F821
    repository: Mapped["Repository"] = relationship(back_populates="symbols")  # noqa: F821
    parent: Mapped["CodeSymbol | None"] = relationship(
        remote_side=[id], back_populates="children"
    )
    children: Mapped[list["CodeSymbol"]] = relationship(back_populates="parent")
    embeddings: Mapped[list["CodeEmbedding"]] = relationship(  # noqa: F821
        back_populates="symbol", cascade="all, delete-orphan"
    )
