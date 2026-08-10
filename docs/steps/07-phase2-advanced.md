# Phase 2: Advanced Features

## Goal

Extend the MVP (Steps 1-6) with three advanced capabilities:
1. **Dependency graph** — map imports/calls between symbols and visualize them
2. **Git diff analysis** — "what breaks if I change this API?" answers
3. **Documentation generation** — auto-generated docs for symbols and repos

---

## Prerequisites

- Steps 1-6 complete and working end-to-end
- A repo indexed and browsable

---

## 7. Dependency Graph

### 7.1 New DB Model

**File**: `backend/src/backend/models/dependency.py`

```python
class Dependency(Base):
    __tablename__ = "dependencies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False)
    source_symbol_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("code_symbols.id", ondelete="CASCADE"), nullable=True)
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=True)
    target_symbol_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("code_symbols.id", ondelete="CASCADE"), nullable=True)
    target_file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))  # "import", "call", "class_extend", "module_import"

    # Can't have two nullable FKs to the same table with cascade in one relationship set —
    # use explicit relationship config or handle via service layer (recommended for simplicity).
```

**Recommendation**: Keep the model simple and resolve edges in the service layer. Source/target can be either a symbol or a file (module-level imports), so both nullable FKs exist.

### 7.2 Alembic Migration

```bash
cd backend
uv run alembic revision --autogenerate -m "add_dependencies"
uv run alembic upgrade head
```

### 7.3 Extraction: Extend `services/parser.py`

Extend the parser to also return **imports and calls** per file:

```python
@dataclass
class ExtractedFile:
    symbols: list[ExtractedSymbol]
    imports: list[ExtractedImport]   # module imports
    calls: list[ExtractedCall]       # calls between symbols

@dataclass
class ExtractedImport:
    source_module: str               # "from x import y" → source is this file
    imported_name: str               # what was imported (or module)
    kind: str                        # "import", "from_import", "require", "import_from_js"

@dataclass
class ExtractedCall:
    caller_name: str                 # symbol making the call
    callee_name: str                 # symbol being called
    line: int
```

**Python queries**:

```
(import_statement (dotted_name) @mod.name)
(import_from_statement
  module_name: (dotted_name) @mod.name
  name: (dotted_name) @imported.name)
(call function: (identifier) @callee)
```

**JS/TS queries**:

```
(import_statement source: (string) @mod)
(import_statement (import_clause ...))
(call_expression function: (identifier) @callee)
(member_expression object: (identifier) @obj property: (property_identifier) @prop)
```

### 7.4 Resolve Edges in `services/indexer.py`

After symbols are stored, resolve references:

1. Build a symbol index: `{name: symbol_record}` per repo (plus module-level map file→module name)
2. For each `ExtractedImport`, look up whether `imported_name` matches a stored symbol or file → create `Dependency` with `kind="import"`
3. For each `ExtractedCall`, check if `callee_name` exists in the symbol index → create `Dependency` with `kind="call"`
4. For classes, record `kind="class_extend"` when a class extends another

### 7.5 Graph Endpoints

**File**: `backend/src/backend/routers/dependencies.py`

```
GET /api/repos/{id}/graph            → full dependency graph (nodes + edges)
GET /api/repos/{id}/symbols/{sid}/dependents   → who depends on this symbol ("what breaks if I change X")
GET /api/repos/{id}/symbols/{sid}/dependencies → what this symbol depends on
```

Response schema:

```python
class GraphNode(BaseModel):
    id: str
    name: str
    kind: str                       # function/class/method/file
    file_path: str
    lines: tuple[int, int] | None

class GraphEdge(BaseModel):
    source: str
    target: str
    kind: str                       # import/call/class_extend

class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
```

### 7.6 Frontend Visualization

**Install**:

```bash
cd frontend
bun add @xyflow/react   # React Flow
```

**File**: `frontend/src/components/dependency-graph.tsx`

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  applyEdgeChanges,
  applyNodeChanges,
  type Node,
  type Edge,
  type NodeChange,
  type EdgeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

interface GraphData {
  nodes: { id: string; name: string; kind: string; file_path: string }[];
  edges: { source: string; target: string; kind: string }[];
}

export default function DependencyGraph({ repoId }: { repoId: string }) {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/repos/${repoId}/graph`)
      .then((r) => r.json())
      .then((data: GraphData) => {
        setNodes(
          data.nodes.map((n) => ({
            id: n.id,
            position: { x: 0, y: 0 }, // layout handled below
            data: { label: `${n.kind} ${n.name}` },
            style: nodeStyle(n.kind),
          }))
        );
        setEdges(
          data.edges.map((e) => ({
            id: `${e.source}-${e.target}`,
            source: e.source,
            target: e.target,
            label: e.kind,
          }))
        );
      });
  }, [repoId]);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => setNodes((nds) => applyNodeChanges(changes, nds) as Node[]),
    []
  );
  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => setEdges((eds) => applyEdgeChanges(changes, eds) as Edge[]),
    []
  );

  return (
    <div style={{ height: "600px" }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        fitView
      >
        <Background />
        <Controls />
        <MiniMap />
      </ReactFlow>
    </div>
  );
}
```

**Note on layout**: React Flow doesn't auto-layout. Either:
- Add `dagre` for hierarchical layout: `bun add dagre @types/dagre`, use `dagre.layout()` to assign positions
- Or use the `@xyflow/react` "auto-layout" helper package

**Node styling by kind**:

```tsx
function nodeStyle(kind: string) {
  switch (kind) {
    case "file": return { background: "#3b82f6", color: "#fff" };
    case "class": return { background: "#8b5cf6", color: "#fff" };
    case "function": return { background: "#10b981", color: "#fff" };
    default: return { background: "#6b7280", color: "#fff" };
  }
}
```

### 7.7 "What Breaks If I Change This?" Flow

New chat capability in `services/rag.py` — when the user asks about impact:

1. Detect intent: question contains "break", "impact", "change", "affect", "what happens if"
2. Identify the target symbol via semantic search
3. Query `Dependency` table for `dependents` (reverse edges) of that symbol
4. Add dependent code chunks to the retrieval context with higher weight
5. Add a prompt instruction: "Analyze the impact of changing X. List affected code with file:line references."

---

## 8. Git Diff Analysis

### 8.1 Diff Extraction Service

**File**: `backend/src/backend/services/diffs.py`

```python
async def get_recent_diffs(repo_dir: Path, max_commits: int = 50) -> list[CommitDiff]:
    """Get recent commits with their diffs."""
    repo = Repo(repo_dir)
    commits = list(repo.iter_commits(max_count=max_commits))

    result = []
    for commit in commits:
        parent = commit.parents[0] if commit.parents else None
        diff = commit.diff(parent, create_patch=True) if parent else commit.diff(create_patch=True)

        # Parse each file's diff
        for d in diff.iter_change_type("M") + diff.iter_change_type("A") + diff.iter_change_type("D"):
            result.append({
                "commit": commit.hexsha[:8],
                "author": commit.author.name,
                "date": commit.committed_datetime.isoformat(),
                "message": commit.message.strip().split("\n")[0],
                "file_path": d.a_path,
                "change_type": d.change_type,  # "M"/"A"/"D"/"R"
                "patch": d.diff.decode("utf-8", errors="replace") if d.diff else None,
                "added_lines": sum(1 for l in d.diff.decode().split("\n") if l.startswith("+") and not l.startswith("+++")),
                "removed_lines": sum(1 for l in d.diff.decode().split("\n") if l.startswith("-") and not l.startswith("---")),
            })
    return result
```

### 8.2 Diff Analysis Endpoints

**File**: `backend/src/backend/routers/diffs.py`

```
GET  /api/repos/{id}/commits               → recent commits with stats
GET  /api/repos/{id}/commits/{sha}         → full diff of a commit
POST /api/repos/{id}/diff/analyze          → LLM analysis of a diff
```

Request body for analyze:

```python
class DiffAnalyzeRequest(BaseModel):
    commit_sha: str | None = None   # analyze a specific commit
    file_path: str | None = None    # OR analyze current changes to a file
```

Response: SSE stream with LLM analysis: "This commit changes X in file Y. The function Z now does A instead of B. This could affect callers in file Q at line L."

### 8.3 Commit History UI

**File**: `frontend/src/components/commit-list.tsx`

- Fetch `GET /api/repos/{id}/commits`
- Each commit: message, author, date, added/removed line counts (+12 −4 styled green/red)
- Click → expand the diff (line-by-line, added lines green, removed lines red)
- Button: "Analyze with AI" → opens chat with prefilled question about the diff

### 8.4 Breakage Detection (the killer feature)

Combine dependency graph + diffs in the RAG prompt:

1. User selects a diff (or asks "what breaks if I change this")
2. Extract changed symbol names from the diff (parse removed/added function names)
3. Query `dependencies` for all dependents of those symbols
4. Feed the dependents' source + the diff into the LLM
5. Response: ranked list of affected callers with file:line + explanation

---

## 9. Documentation Generation

### 9.1 Symbol Doc Generation

**File**: `backend/src/backend/services/docs.py`

```python
async def generate_symbol_doc(symbol: CodeSymbol) -> str:
    """Generate markdown documentation for a single symbol."""
    client = AsyncOpenAI(...)

    prompt = f"""You are a technical documentation writer.
Generate concise, accurate markdown documentation for this code symbol.

File: {symbol.file_path}
Type: {symbol.kind}
Name: {symbol.name}
Signature: {symbol.signature}

```{symbol.language}
{symbol.source_text}
```

Include: purpose, parameters, return value, side effects, and a usage example."""

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1024,
    )
    return response.choices[0].message.content
```

### 9.2 Repo README Generation

```python
async def generate_repo_readme(repo_id: uuid.UUID) -> str:
    """Generate a project README from the repo's indexed symbols."""
    # 1. Get all top-level symbols grouped by file
    # 2. Summarize architecture: entry points, core modules, data flow
    # 3. LLM writes structured README: overview, architecture, key modules,
    #    getting started, API reference (linking file:line)
```

### 9.3 Endpoints

```
POST /api/repos/{id}/docs/readme         → generate repo README (returns markdown)
POST /api/symbols/{id}/doc               → generate doc for one symbol
GET  /api/repos/{id}/docs                → cached generated docs
```

Cache generated docs in a `generated_docs` table (repo_id, symbol_id nullable, content, kind, created_at) to avoid regenerating on every view.

### 9.4 UI

- Symbol docs shown in a collapsible panel below the code viewer ("AI Documentation" tab)
- Repo README rendered in a "README" tab of the repo browser (render markdown with `react-markdown`)
- "Generate README" button on the repo page

```bash
cd frontend
bun add react-markdown remark-gfm
```

---

## 10. Additional Nice-to-Haves (Optional)

| Feature | Description |
|---|---|
| **Multi-language support** | Add `tree-sitter-go`, `tree-sitter-rust`, `tree-sitter-java` etc. Map extensions in `services/github.py` + add language handlers in `services/parser.py` |
| **Incremental re-indexing** | Compare `content_hash` of files between index runs; only re-parse changed files |
| **Background job queue** | Replace FastAPI `BackgroundTasks` with a real queue (arq/redis) for production indexing |
| **Private repo support** | Use the GitHub OAuth token server-side for cloning private repos |
| **Auth enforcement** | Protect `/api/repos` with JWT when multi-user support lands |
| **Code actions** | "Explain this function", "Find usages", "Generate test" quick buttons on symbols |
| **Blame view** | git blame per line |

---

## Definition of Done (Phase 2)

- [ ] `dependencies` table + migration + graph endpoints
- [ ] Parser extracts imports and calls
- [ ] Indexer resolves dependency edges
- [ ] Dependency graph renders in frontend with React Flow
- [ ] "What breaks if I change X" answers reference affected code
- [ ] Commit list + diff viewer UI
- [ ] Diff analysis via LLM
- [ ] Symbol + repo documentation generation
- [ ] README tab renders generated docs
