# Step 3: Embeddings Service & Indexing Pipeline

## Goal

Create two services:
1. `backend/src/backend/services/embeddings.py` — generates vector embeddings via OpenAI-compatible API
2. `backend/src/backend/services/indexer.py` — orchestrates the full pipeline: clone → parse → embed → store

---

## Prerequisites

- Step 1 complete (DB, models, `services/github.py`)
- Step 2 complete (`services/parser.py` with `parse_file()`)

---

## What to Build

### 3.1 Embeddings Service

**File**: `backend/src/backend/services/embeddings.py`

#### OpenAI Client Setup

```python
from openai import AsyncOpenAI
from backend.config import settings

def get_openai_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_api_base,
    )
```

#### Single Embedding

```python
async def get_embedding(text: str) -> list[float]:
    """Generate embedding for a single text string."""
    client = get_openai_client()
    response = await client.embeddings.create(
        model=settings.openai_embedding_model,
        input=text,
    )
    return response.data[0].embedding
```

#### Batch Embeddings

The OpenAI embeddings API supports batching (multiple inputs in one call). Batch to stay under token limits.

```python
async def get_embeddings_batch(texts: list[str], batch_size: int = 100) -> list[list[float]]:
    """Generate embeddings for multiple texts in batches."""
    client = get_openai_client()
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        response = await client.embeddings.create(
            model=settings.openai_embedding_model,
            input=batch,
        )
        # Sort by index to maintain order
        sorted_data = sorted(response.data, key=lambda x: x.index)
        all_embeddings.extend([d.embedding for d in sorted_data])

    return all_embeddings
```

#### Text Preparation

Before embedding, prepare the text to give the model better context:

```python
def prepare_symbol_text(
    symbol_name: str,
    symbol_kind: str,
    file_path: str,
    source_text: str,
    docstring: str | None,
    signature: str | None,
) -> str:
    """Build a text representation of a code symbol for embedding.

    Includes metadata like file path and symbol kind to improve
    search relevance.
    """
    parts = [
        f"File: {file_path}",
        f"Type: {symbol_kind}",
        f"Name: {symbol_name}",
    ]
    if signature:
        parts.append(f"Signature: {signature}")
    if docstring:
        parts.append(f"Documentation: {docstring}")
    parts.append(f"Code:\n{source_text}")

    return "\n".join(parts)
```

This structured format helps the embedding model understand the role of different parts of the text, improving semantic search quality.

#### Token Truncation

Embedding models have a max token limit (8191 for `text-embedding-3-small`). For very large functions/classes, truncate:

```python
MAX_EMBED_CHARS = 24_000  # ~6000 tokens, safe margin

def truncate_for_embedding(text: str) -> str:
    if len(text) <= MAX_EMBED_CHARS:
        return text
    return text[:MAX_EMBED_CHARS] + "\n... [truncated]"
```

---

### 3.2 Indexer Service

**File**: `backend/src/backend/services/indexer.py`

This is the orchestrator that ties everything together. It runs as a **background task** triggered by `POST /api/repos/{id}/index`.

#### Entry Point

```python
async def run_indexing(repo_id: uuid.UUID) -> None:
    """Main indexing pipeline. Runs as a background task.

    Steps:
    1. Update repo status to 'cloning'
    2. Clone/pull the repository
    3. Update repo status to 'indexing'
    4. Walk all source files
    5. For each file:
       a. Parse with tree-sitter to extract symbols
       b. Store file record in DB
       c. Store symbol records in DB
    6. Generate embeddings for all symbols in batches
    7. Store embedding records in DB
    8. Update repo status to 'ready'
    """
```

#### Important: Separate DB Session

Since this runs in a background task (outside the request lifecycle), it needs its own database session:

```python
from backend.db import async_session

async def run_indexing(repo_id: uuid.UUID) -> None:
    async with async_session() as db:
        try:
            await _do_indexing(db, repo_id)
        except Exception as e:
            logger.exception(f"Indexing failed for repo {repo_id}")
            # Update status to error
            repo = await db.get(Repository, repo_id)
            if repo:
                repo.status = RepoStatus.error
                repo.error_message = str(e)
                await db.commit()
```

#### Pipeline Implementation

```python
async def _do_indexing(db: AsyncSession, repo_id: uuid.UUID) -> None:
    repo = await db.get(Repository, repo_id)
    if not repo:
        return

    # Step 1: Clone
    repo.status = RepoStatus.cloning
    await db.commit()

    repo_dir = clone_repo(repo.github_url, repo.owner, repo.name)
    repo.default_branch = get_default_branch(repo_dir)

    # Step 2: Index
    repo.status = RepoStatus.indexing
    await db.commit()

    # Clear old data for re-indexing
    await _clear_repo_data(db, repo_id)

    # Step 3: Walk and parse files
    source_files = walk_source_files(repo_dir)
    all_symbols_for_embedding = []  # list of (symbol_db_obj, prepared_text)

    for file_info in source_files:
        # Create File record
        file_record = File(
            repo_id=repo_id,
            path=file_info["path"],
            language=file_info["language"],
            content=file_info["content"],
            content_hash=hashlib.sha256(file_info["content"].encode()).hexdigest(),
        )
        db.add(file_record)
        await db.flush()

        # Parse with tree-sitter
        extracted = parse_file(file_info["content"], file_info["language"])

        # Store symbols
        for symbol in extracted:
            sym_record = _create_symbol_record(
                symbol, file_record.id, repo_id, parent_id=None
            )
            db.add(sym_record)
            await db.flush()

            # Prepare text for embedding
            text = prepare_symbol_text(
                symbol_name=symbol.name,
                symbol_kind=symbol.kind,
                file_path=file_info["path"],
                source_text=symbol.source_text,
                docstring=symbol.docstring,
                signature=symbol.signature,
            )
            all_symbols_for_embedding.append((sym_record, text, file_info["path"]))

            # Also process child symbols (methods in classes)
            for child in symbol.children:
                child_record = _create_symbol_record(
                    child, file_record.id, repo_id, parent_id=sym_record.id
                )
                db.add(child_record)
                await db.flush()

                child_text = prepare_symbol_text(
                    symbol_name=child.name,
                    symbol_kind=child.kind,
                    file_path=file_info["path"],
                    source_text=child.source_text,
                    docstring=child.docstring,
                    signature=child.signature,
                )
                all_symbols_for_embedding.append((child_record, child_text, file_info["path"]))

    await db.commit()

    # Step 4: Generate embeddings in batches
    if all_symbols_for_embedding:
        texts = [truncate_for_embedding(t) for _, t, _ in all_symbols_for_embedding]
        embeddings = await get_embeddings_batch(texts)

        for (sym_record, text, file_path), embedding in zip(
            all_symbols_for_embedding, embeddings
        ):
            emb_record = CodeEmbedding(
                symbol_id=sym_record.id,
                repo_id=repo_id,
                chunk_text=text,
                file_path=file_path,
                symbol_name=sym_record.name,
                symbol_kind=sym_record.kind,
                embedding=embedding,
            )
            db.add(emb_record)

        await db.commit()

    # Step 5: Mark as ready
    repo.status = RepoStatus.ready
    repo.indexed_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info(f"Indexing complete for {repo.owner}/{repo.name}: "
                f"{len(source_files)} files, {len(all_symbols_for_embedding)} symbols")
```

#### Helper: Clear Old Data

For re-indexing, delete previous files/symbols/embeddings:

```python
async def _clear_repo_data(db: AsyncSession, repo_id: uuid.UUID) -> None:
    """Delete all indexed data for a repo (for re-indexing)."""
    from sqlalchemy import delete
    await db.execute(delete(CodeEmbedding).where(CodeEmbedding.repo_id == repo_id))
    await db.execute(delete(CodeSymbol).where(CodeSymbol.repo_id == repo_id))
    await db.execute(delete(File).where(File.repo_id == repo_id))
    await db.commit()
```

#### Helper: Create Symbol Record

```python
def _create_symbol_record(
    symbol: ExtractedSymbol,
    file_id: uuid.UUID,
    repo_id: uuid.UUID,
    parent_id: uuid.UUID | None,
) -> CodeSymbol:
    return CodeSymbol(
        file_id=file_id,
        repo_id=repo_id,
        name=symbol.name,
        kind=symbol.kind,
        start_line=symbol.start_line,
        end_line=symbol.end_line,
        source_text=symbol.source_text,
        signature=symbol.signature,
        docstring=symbol.docstring,
        parent_id=parent_id,
    )
```

---

## Error Handling

The indexer should handle errors gracefully:

1. **Clone failures** — network errors, private repos (no auth yet). Catch and set `status=error` with a message.
2. **Parse failures** — tree-sitter is error-tolerant, but catch exceptions per-file and skip bad files rather than failing the whole index.
3. **Embedding API failures** — rate limits, network errors. Implement retry with exponential backoff (or use `tenacity`). On persistent failure, set `status=error`.
4. **Out of memory** — very large repos might produce thousands of symbols. Process in chunks and commit periodically rather than holding everything in memory.

---

## Testing

After implementing, test the full pipeline:

1. Start the API: `uv run python src/backend/main.py`
2. Connect a small repo:
   ```bash
   curl -X POST http://localhost:8000/api/repos \
     -H "Content-Type: application/json" \
     -d '{"github_url": "https://github.com/expresjs/express"}'
   ```
3. Trigger indexing (use the repo ID from the response):
   ```bash
   curl -X POST http://localhost:8000/api/repos/{id}/index
   ```
4. Poll status:
   ```bash
   curl http://localhost:8000/api/repos/{id}/index/status
   ```
5. Verify data in DB:
   ```bash
   docker compose exec db psql -U codebase -d codebase_intelligence \
     -c "SELECT count(*) FROM files; SELECT count(*) FROM code_symbols; SELECT count(*) FROM code_embeddings;"
   ```

**Tip**: For testing without burning embedding API credits, temporarily return random vectors in `get_embeddings_batch()`:
```python
import random
return [[random.random() for _ in range(1536)] for _ in texts]
```

---

## Definition of Done

- [ ] `services/embeddings.py` exists with `get_embedding()`, `get_embeddings_batch()`, `prepare_symbol_text()`
- [ ] `services/indexer.py` exists with `run_indexing()`
- [ ] Connecting a repo + triggering index completes without errors
- [ ] `files`, `code_symbols`, and `code_embeddings` tables are populated
- [ ] Repo status transitions: pending → cloning → indexing → ready
- [ ] Errors are caught and stored in `repo.error_message`
- [ ] Re-indexing clears old data before writing new data
