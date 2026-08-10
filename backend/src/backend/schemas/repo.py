from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class RepoConnect(BaseModel):
    github_url: str = Field(..., examples=["https://github.com/owner/repo"])


class RepoResponse(BaseModel):
    id: uuid.UUID
    github_url: str
    name: str
    owner: str
    default_branch: str
    status: str
    error_message: str | None = None
    indexed_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RepoListResponse(BaseModel):
    repositories: list[RepoResponse]


class FileTreeNode(BaseModel):
    name: str
    path: str
    type: str  # "file" or "directory"
    language: str | None = None
    children: list[FileTreeNode] | None = None


class FileContentResponse(BaseModel):
    path: str
    language: str | None
    content: str
    symbols: list[SymbolInfo] = []


class SymbolInfo(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    start_line: int
    end_line: int
    signature: str | None = None
    docstring: str | None = None

    model_config = {"from_attributes": True}


# Rebuild FileContentResponse so it can reference SymbolInfo
FileContentResponse.model_rebuild()
