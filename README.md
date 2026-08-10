# Codebase Intelligence

Connect a GitHub repository, index it with tree-sitter, search it semantically with
pgvector, and chat with an AI about its code.

Codebase Intelligence turns any GitHub repo into a queryable, searchable, AI-ready
knowledge base. It parses source code into symbols (functions, classes, methods),
extracts how they relate to each other (imports, calls, inheritance), embeds every
symbol with a vector model, and lets you:

- **Browse** the file tree and read code with syntax highlighting
- **Search** the codebase semantically — ask "where is rate limiting implemented?"
  and get the right functions back, not just keyword matches
- **Chat** with the codebase — a RAG pipeline retrieves the most relevant symbols
  for your question and streams an answer from an LLM
- **Explore dependencies** — interactive graph of which symbol calls/imports/extends
  which
- **Review history** — commit list with AI-generated summaries of what each change
  did and why it matters
- **Get documentation** — LLM-generated docs for functions/classes, plus
  README-style overview of the repo

## Architecture

```
Next.js (Dashboard, Repo Browser, Code Viewer, AI Chat, Search, Auth)
        │  HTTPS
        ▼
FastAPI (repos CRUD, indexing trigger, file tree/content, semantic search,
         SSE chat, auth)
        │
        ├── Tree-sitter          symbol extraction (functions/classes/methods,
        │                        imports, calls, inheritance)
        ├── NVIDIA nemotron-3-embed-1b    embeddings (2048 dims)
        ├── OpenAI-compatible chat API    (e.g. deepseek via vcliproxy)
        └── SQLAlchemy async → PostgreSQL + pgvector (embeddings in code_embeddings)
```

| Component | Technology |
|---|---|
| Frontend | Next.js 16 (App Router, TypeScript, Tailwind CSS 4, Turbopack) |
| Backend | Python 3.13, FastAPI, SQLAlchemy 2 (async) |
| Database | PostgreSQL 17 + pgvector |
| Parsing | tree-sitter (Python, JavaScript, TypeScript) |
| Embeddings | NVIDIA nemotron-3-embed-1b (2048-dim vectors) |
| Chat | OpenAI-compatible endpoint (SSE streaming) |

### Data flow

1. **Connect** — user adds a GitHub repo URL (`https://github.com/owner/name`).
2. **Clone** — the backend clones the repo shallowly (`--depth 1`) into a
   per-user folder (`~/.derive/u{user_id}/{owner}__{name}`).
3. **Parse** — tree-sitter walks every source file and extracts symbols plus
   their relationships (imports, calls, inheritance).
4. **Embed** — each symbol (with its code context) is sent to the embedding model
   in batches; the 2048-dim vectors are stored in pgvector.
5. **Serve** — search, chat, dependency graph, diffs, and docs all query the
   indexed data.

### Why 2048-dim vectors and no ANN index?

The embedding model produces 2048-dimensional vectors. pgvector's ivfflat and
hnsw approximate indexes cap at 2000 dimensions, so `code_embeddings` uses exact
cosine similarity (`<=>` operator) instead. This is plenty fast for typical
codebases (<100k symbols).

## Database schema

8 tables, managed exclusively through Alembic migrations:

| Table | Purpose |
|---|---|
| `users` | Auth accounts (username + password, single session token) |
| `repositories` | Connected repos, owned by a user; status machine + error tracking |
| `files` | Every indexed source file (path, language, content) |
| `symbols` | Functions/classes/methods with type, line ranges, docstring |
| `code_embeddings` | pgvector embeddings per symbol (2048 dims, cosine search) |
| `dependencies` | Symbol-to-symbol edges (imports, calls, inheritance) |
| `chat_sessions` / `chat_messages` | Chat history per user |
| `generated_docs` | LLM-generated docs, cached per symbol/repo |

### Repository status machine

`pending → cloning → indexing → ready` (or `error`, with an error message).
Status is surfaced at `GET /api/repos/{id}/index/status`.

## Authentication

Simple username/password auth (no OAuth needed):

- Default user: **admin / admin** (seeded on first startup; change the password
  via the database or `seed_default_user` in the backend).
- Password hashing: PBKDF2-HMAC-SHA256 (200,000 iterations, per-user salt).
- Login returns an opaque session token; the frontend stores it in
  `localStorage` (`auth_token`) and sends it as `Authorization: Bearer ...` on
  every request.
- **All repos are scoped to the owning user** — you only ever see your own.

## API

All endpoints are under `/api` and require `Authorization: Bearer <token>`
(obtained from `POST /api/auth/login`).

### Auth

| Method | Path | Description |
|---|---|---|
| POST | `/auth/login` | Login with username/password → `{token, user}` |
| POST | `/auth/logout` | Invalidate the current session token |
| GET | `/auth/me` | Current user info |

### Repos & indexing

| Method | Path | Description |
|---|---|---|
| GET | `/repos` | List my repos |
| POST | `/repos` | Connect a new repo (body: `{github_url}`) |
| GET | `/repos/{id}` | Repo details |
| DELETE | `/repos/{id}` | Remove repo + all indexed data (cascade) |
| POST | `/repos/{id}/index` | Trigger indexing (runs as a background task) |
| GET | `/repos/{id}/index/status` | `pending/cloning/indexing/ready/error` |
| GET | `/repos/{id}/tree` | File tree for the code browser |
| GET | `/repos/{id}/files/{path}` | File content with symbols |

### Search & analysis

| Method | Path | Description |
|---|---|---|
| GET | `/search?q=...&repo_id=...` | Semantic (pgvector) search over symbols |
| GET | `/repos/{id}/graph` | Full dependency graph for the repo |
| GET | `/repos/{id}/symbols/{symbol_id}/dependencies` | What a symbol depends on |
| GET | `/repos/{id}/symbols/{symbol_id}/dependents` | What depends on a symbol |
| POST | `/symbols/{symbol_id}/doc` | Generate/cache LLM docs for a symbol |
| GET | `/repos/{id}/docs` | Cached generated docs for a repo |
| GET | `/repos/{id}/commits` | Commit history (unshallows clone on demand) |
| GET | `/repos/{id}/commits/{sha}` | Commit detail |
| POST | `/repos/{id}/diff/analyze` | LLM analysis of a commit diff |

### Chat

| Method | Path | Description |
|---|---|---|
| GET | `/chat/sessions` | List chat sessions |
| GET | `/chat/sessions/{id}` | Session + messages |
| POST | `/chat` | Send a message → SSE stream of `{"text": ...}` chunks |

The chat endpoint is a RAG pipeline: your question is embedded, the most
similar symbols are retrieved from pgvector, their code is packed into a prompt,
and the LLM's answer streams back as Server-Sent Events (`data:` payloads are
JSON-encoded; `event: done` signals completion).

## Getting started

### Prerequisites

- Python 3.13 + [uv](https://docs.astral.sh/uv/)
- Node.js 20+ + [bun](https://bun.sh/)
- Docker (for PostgreSQL + pgvector)

### 1. Database

```bash
docker compose up -d          # pgvector Postgres on :5432
```

### 2. Backend

```bash
cd backend
cp ../.env.example .env       # fill in API keys (see below)
uv sync                       # install dependencies into .venv
uv run alembic upgrade head   # apply migrations
uv run python src/backend/main.py   # dev server on :8001
```

### 3. Frontend

```bash
cd frontend
bun install
bun run dev                   # dev server on http://localhost:3000
```

### Configuration (backend/.env)

| Variable | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | Postgres connection string | `postgresql+asyncpg://codebase:codebase@localhost:5432/codebase_intelligence` |
| `OPENAI_API_BASE` | Chat endpoint (OpenAI-compatible) | `https://vcliproxyapi.duckdns.org` |
| `OPENAI_API_KEY` | Chat API key | (required) |
| `OPENAI_MODEL` | Chat model | `deepseek-v4-flash-free` |
| `OPENAI_EMBEDDING_BASE` | Embedding endpoint | `https://integrate.api.nvidia.com/v1` |
| `OPENAI_EMBEDDING_API_KEY` | Embedding API key | (required) |
| `OPENAI_EMBEDDING_MODEL` | Embedding model | `nvidia/nemotron-3-embed-1b` |
| `REPOS_DIR` | Where clones live (`~` expands) | `~/.derive` |
| `FRONTEND_URL` | CORS allowed origins, comma-separated | `http://localhost:3000` |

> Chat and embeddings use **separate** endpoints/keys on purpose — swap in any
> OpenAI-compatible chat provider without touching your embedding setup.

## Repo layout

```
├── docker-compose.yml        # pgvector Postgres (port 5432)
├── .env.example              # env template
├── docs/steps/               # step-by-step implementation guides (01–07)
├── backend/                  # Python API (uv)
│   ├── alembic/              # migrations (async env.py)
│   └── src/backend/
│       ├── main.py           # FastAPI app + router registration
│       ├── config.py         # pydantic-settings (split chat/embedding config)
│       ├── db.py             # async engine/session/Base
│       ├── models/           # SQLAlchemy models (8 tables)
│       ├── schemas/          # Pydantic request/response models
│       ├── routers/          # auth, repos, index, search, chat, files,
│       │                     # dependencies, diffs, docs
│       └── services/         # github, auth, parser, embeddings, indexer,
│                             # search, rag, diffs, docs
└── frontend/                 # Next.js app (bun)
    └── src/
        ├── app/              # pages: dashboard, repo/[id], login
        ├── components/       # file-tree, code-viewer, chat-panel, search-bar,
        │                     # dependency-graph, commit-list, generated-docs, ...
        └── lib/api.ts        # typed API client for all endpoints
```

## Development conventions

- **Python deps**: `uv add <package>` in `backend/` — never pip-install directly.
- **Node deps**: `bun add <package>` — never npm/pnpm.
- **Database**: all schema changes via Alembic migrations — never hand-edit tables.
- **Streaming**: SSE events are JSON-encoded (`{"text": "..."}`); errors use
  `event: error`, completion uses `event: done`.
- **Indexing** runs as a FastAPI `BackgroundTask` with its own DB session — the
  trigger endpoint itself is read-only (an uncommitted `UPDATE` in the request
  would hold a row lock the task blocks on while the request's post-yield commit
  is chained behind the task's execution — a permanent deadlock).
- **Embedding retries**: 5 attempts with exponential backoff, batch size 50.
- **Git operations** run inside `asyncio.to_thread()` — never call them directly
  from async code.
- **Clones are shallow** (`--depth 1`). The commit-history feature unshallows
  on demand, once, when you first open the Commits tab.

## Production deployment

The live deployment:

| Component | Location |
|---|---|
| Frontend | Vercel (static export, `NEXT_PUBLIC_API_URL` baked in at build) |
| Backend | systemd unit `codebase-intelligence` → uvicorn on `:8001` |
| Database | pgvector Postgres in Docker on the same host |

```bash
sudo systemctl restart codebase-intelligence   # restart backend
sudo journalctl -u codebase-intelligence -f    # follow logs
```

## Roadmap / known limitations

- No rate limiting on API endpoints (acceptable for an initial release).
- Single active session per user (token stored on the user row).
- Exact cosine search instead of ANN indexes (2048-dim embedding model).
- End-to-end automated test suite still TODO.

## License

[MIT](LICENSE)
