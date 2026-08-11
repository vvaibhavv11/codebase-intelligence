from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator


class ChatRequest(BaseModel):
    repo_id: uuid.UUID
    session_id: uuid.UUID | None = None
    message: str


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionResponse(BaseModel):
    id: uuid.UUID
    repo_id: uuid.UUID
    title: str | None
    created_at: datetime
    messages: list[ChatMessageResponse] = []

    model_config = {"from_attributes": True}


class ChatSessionSummary(BaseModel):
    """Lightweight session representation (list view) — no messages loaded."""

    id: uuid.UUID
    repo_id: uuid.UUID
    title: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionListResponse(BaseModel):
    sessions: list[ChatSessionSummary]


class ChatSessionUpdate(BaseModel):
    title: str

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title cannot be empty")
        if len(v) > 500:
            raise ValueError("Title cannot exceed 500 characters")
        return v
