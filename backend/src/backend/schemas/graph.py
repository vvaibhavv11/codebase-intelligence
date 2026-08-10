from __future__ import annotations

from pydantic import BaseModel


class GraphNode(BaseModel):
    id: str
    name: str
    kind: str  # function/class/method/file
    file_path: str
    lines: tuple[int, int] | None = None


class GraphEdge(BaseModel):
    source: str
    target: str
    kind: str  # import/call/class_extend/module_import


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
