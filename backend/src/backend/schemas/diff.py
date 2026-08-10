from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CommitSummary(BaseModel):
    sha: str
    author: str
    date: datetime
    message: str
    files_changed: int
    added_lines: int
    removed_lines: int


class FileDiff(BaseModel):
    file_path: str
    change_type: str  # M/A/D/R
    patch: str | None = None
    added_lines: int = 0
    removed_lines: int = 0


class CommitDiff(BaseModel):
    sha: str
    author: str
    date: datetime
    message: str
    files: list[FileDiff]


class DiffAnalyzeRequest(BaseModel):
    commit_sha: str | None = None  # analyze a specific commit
    file_path: str | None = None   # OR analyze current changes to a file
