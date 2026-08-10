# Step 4: Semantic Search Service

## Goal

Create `backend/src/backend/services/search.py` — a service that performs semantic (vector similarity) search over indexed code symbols using pgvector.

---

## Prerequisites

- Step 1 complete (DB with `code_embeddings` table containing `Vector(1536)` column)
- Step 3 complete (`services/embeddings.py` with `get_embedding()`)
- At least one repository successfully indexed (embeddings stored in DB)

---

## What to Build

### File: `backend/src/backend/services/search.py`

### 4.1 Core Search Function

```python
async def search_code(
    db: AsyncSession,
    repo_id: uuid.UUID,
    query: str,
    limit: int = 20,
) -> list[SearchResult]:
```

**Algorithm:**
1. Embed the user's query using `get_embedding()`
2. Run a pgvector cosine distance query against `code_embeddings` filtered by `repo_id`
3. Join with `code_symbols` to get symbol metadata
4. Return ranked results with scores

### 4.2 pgvector Query

pgvector supports three distance operators:
- `<->` — L2 distance (Euclidean)
- `<#>` — negative inner product
- `<=>` — cosine distance (1 - cosine_similarity)

Use **cosine distance** (`<=>`), which is best for text embeddings.

```python
from sqlalchemy import select, func
from pgvector.sqlalchemy import Vector

async def search_code(
    db: AsyncSession,
    repo_id: uuid.UUID,
    query: str,
    limit: int = 20,
) -> list[SearchResult]:
    # Step 1: Embed the query
    query_embedding = await get_embedding(query)

    # Step 2: Vector similarity search
    distance = CodeEmbedding.embedding.cosine_distance(query_embedding)

    stmt = (
        select(
            CodeEmbedding,
            CodeSymbol,
            distance.label("distance"),
        )
        .join(CodeSymbol, CodeEmbedding.symbol_id == CodeSymbol.id)
        .where(CodeEmbedding.repo_id == repo_id)
        .order_by(distance)
        .limit(limit)
    )

    result = await db.execute(stmt)
    rows = result.all()

    # Step 3: Map to response schema
    return [
        SearchResult(
            symbol_id=symbol.id,
            symbol_name=symbol.name,
            symbol_kind=symbol.kind,
            file_path=embedding.file_path or "",
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            source_preview=_truncate_source(symbol.source_text, max_lines=15),
            score=round(1 - dist, 4),  # Convert distance to similarity score
        )
        for embedding, symbol, dist in rows
    ]
```

### 4.3 Source Preview Helper

Show a truncated preview of the source code in search results:

```python
def _truncate_source(source: str, max_lines: int = 15) -> str:
    """Truncate source code to a preview for search results."""
    lines = source.split("\n")
    if len(lines) <= max_lines:
        return source
    return "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"
```

### 4.4 Score Threshold (Optional Enhancement)

Filter out low-relevance results:

```python
MIN_SIMILARITY = 0.3  # Cosine distance > 0.7 → too dissimilar

# Add to the query:
.where(distance < (1 - MIN_SIMILARITY))
```

This prevents returning garbage results for queries that don't match anything.

### 4.5 How the Router Calls This

The router at `backend/src/backend/routers/search.py` already exists and calls:

```python
from backend.services.search import search_code
results = await search_code(db, repo_id, q, limit)
```

It expects `search_code` to return a list of `SearchResult` objects (from `backend.schemas.search`). Make sure the function returns exactly that type.

---

## Understanding pgvector Distance

| Query distance | Similarity | Meaning |
|---|---|---|
| 0.0 | 1.0 | Identical vectors |
| 0.3 | 0.7 | Very similar |
| 0.5 | 0.5 | Somewhat related |
| 0.7 | 0.3 | Weak match |
| 1.0 | 0.0 | Orthogonal (unrelated) |

The `<=>` operator returns **cosine distance** (0 to 2), where lower = more similar. We convert to similarity (`1 - distance`) for the API response.

---

## Testing

### Manual test via curl

```bash
# Search an indexed repo
curl "http://localhost:8000/api/search?q=authenticate+user&repo_id={id}&limit=5"
```

Expected response:
```json
{
  "query": "authenticate user",
  "results": [
    {
      "symbol_id": "...",
      "symbol_name": "authenticate",
      "symbol_kind": "function",
      "file_path": "src/auth.py",
      "start_line": 42,
      "end_line": 67,
      "source_preview": "def authenticate(username, password):\n    ...",
      "score": 0.8234
    }
  ],
  "total": 5
}
```

### Verification queries

Test a variety of query types to ensure semantic search works:

1. **Exact name**: `"calculate_total"` — should find the function by name
2. **Natural language**: `"how is authentication handled"` — should find auth-related code
3. **Conceptual**: `"error handling"` — should find try/except blocks, error handlers
4. **Unrelated**: `"recipe for chocolate cake"` — should return low scores or empty results

---

## Performance Notes

- Without an index, pgvector does **exact nearest-neighbor search** (sequential scan). This is fine for small-to-medium repos (< 50K embeddings).
- For large repos, create an **IVFFlat** or **HNSW** index after data is loaded:
  ```sql
  CREATE INDEX ON code_embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
  ```
  Or with HNSW (better recall, slower build):
  ```sql
  CREATE INDEX ON code_embeddings
    USING hnsw (embedding vector_cosine_ops);
  ```
- The model definition in `models/embedding.py` already has an IVFFlat index defined in `__table_args__`, but it was skipped in the initial migration because IVFFlat requires existing data. After the first repo is indexed, you could run this via a manual Alembic migration or raw SQL.

---

## Definition of Done

- [ ] `services/search.py` exists with `search_code()` function
- [ ] Returns `list[SearchResult]` matching the Pydantic schema
- [ ] Uses pgvector cosine distance for ranking
- [ ] `GET /api/search?q=...&repo_id=...` returns relevant results
- [ ] Results include symbol name, kind, file path, line numbers, and source preview
- [ ] Score is a similarity value between 0 and 1 (higher = better)
