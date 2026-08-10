from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class GeneratedDocResponse(BaseModel):
    id: uuid.UUID
    repo_id: uuid.UUID
    symbol_id: uuid.UUID | None
    content: str
    kind: str  # "symbol_doc", "readme"
    created_at: datetime

    model_config = {"from_attributes": True}


class GeneratedDocListResponse(BaseModel):
    docs: list[GeneratedDocResponse]
