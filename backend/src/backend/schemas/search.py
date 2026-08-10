from __future__ import annotations

import uuid

from pydantic import BaseModel


class SearchRequest(BaseModel):
    query: str
    repo_id: uuid.UUID
    limit: int = 20


class SearchResult(BaseModel):
    symbol_id: uuid.UUID
    symbol_name: str
    symbol_kind: str
    file_path: str
    start_line: int
    end_line: int
    source_preview: str
    score: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    total: int
