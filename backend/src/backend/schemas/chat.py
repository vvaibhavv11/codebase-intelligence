from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


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


class ChatSessionListResponse(BaseModel):
    sessions: list[ChatSessionResponse]
