# AGENTS.md

Guidance for AI coding agents working in this repository.

## Project Overview

`codebase-intelligence` — a monorepo for a codebase analysis/intelligence tool.
Connect a GitHub repo, index its source code with tree-sitter, search it semantically (pgvector), and **chat about it** (RAG + LLM). The AI chat is the primary user experience — the code browser is a secondary, on-demand panel.

- **`backend/`** — Python 3.13 FastAPI API, managed with [uv](https://docs.astral.sh/uv/)
- **`frontend/`** — Next.js 16 (App Router, TypeScript, Tailwind CSS 4, Turbopack), managed with [bun](https://bun.sh/)

## Architecture

```
Next.js (AI Chat [main view], Code Browser [on-demand panel], Dashboard, Search, Auth)
        │
        ▼
FastAPI (repos CRUD, indexing trigger, file tree/content, semantic search, SSE chat, Auth)
        │
        ├── Tree-sitter (symbol extraction across 11 languages + imports/calls/inheritance)
        ├── NVIDIA nemotron-3-embed-1b (embeddings, 2048 dims)
        ├── OpenAI-compatible chat API (vcliproxy — deepseek-v4-flash-free)
        └── SQLAlchemy async → PostgreSQL + pgvector (embeddings in `code_embeddings`)
```

## Current Build Status

| Area | Status |
|---|---|
| Docker Compose (pgvector/pgvector:pg17) | **Done** — `docker compose up -d` |
| Backend infra (FastAPI, config, db, CORS) | **Done** |
| ORM models (repos, files, symbols, embeddings, chat, dependencies, generated_docs) | **Done** — 8 tables |
| Alembic migrations (3 applied: initial + deps/docs + embedding dim) | **Done** |
| Pydantic schemas + all 9 routers | **Done** |
| `services/github.py` (clone/pull/walk files — indexes all text files, skips binaries) | **Done** |
| `services/parser.py` (tree-sitter: symbols + imports/calls/inheritance across 11 languages) | **Done** |
| `services/embeddings.py` (NVIDIA nemotron-3-embed-1b, 2048 dims, retry w/ backoff) | **Done** |
| `services/indexer.py` (clone→parse→embed→store + dependency resolution) | **Done** |
| `services/search.py` (pgvector cosine similarity) | **Done** |
| `services/rag.py` (RAG chat + SSE streaming + impact analysis) | **Done** |
| `services/diffs.py` (git commit history + LLM diff analysis) | **Done** |
| `services/docs.py` (LLM doc generation + caching) | **Done** |
| Frontend (dashboard, browser, viewer, chat, search, login) | **Done** — builds clean |
| Frontend chat-first layout (chat is main view, code browser is on-demand right panel) | **Done** |
| Frontend chat markdown rendering (ReactMarkdown + remark-gfm + shiki syntax highlighting) | **Done** |
| Clickable source chips in chat (AI answer → open referenced function in code panel) | **Done** |
| Frontend Phase 2 (dependency graph, commit list, generated docs) | **Done** |
| Auth hardening (token validation on mount, 401 auto-redirect via `authFetch`) | **Done** |
| Production deployment (Vercel frontend + systemd backend on 8001 + nginx) | **Done** — see "Production" below |
| End-to-end testing (index a real repo, verify all endpoints) | **TODO** |

## Production

Live deployment (as of Aug 2026):

| Component | URL / Location |
|---|---|
| Frontend | **https://codebase-intelligence-jet.vercel.app** (Vercel project `codebase-intelligence`, vercel.com under vvaibhavv11) |
| Backend API | **https://vuptime.duckdns.org** (nginx → `127.0.0.1:8001`) |
| Backend health | `https://vuptime.duckdns.org/api/health` |
| GitHub repo | `vvaibhavv11/codebase-intelligence` (public, branch `main`) |
| Database | pgvector Postgres in Docker on the same host (`localhost:5432`) |

### Backend process (systemd)

The production backend runs as a systemd service named `codebase-intelligence`:

```bash
sudo systemctl status codebase-intelligence   # check status/logs
sudo systemctl restart codebase-intelligence  # restart after .env changes
sudo journalctl -u codebase-intelligence -f   # follow logs
```

- Executes `.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8001 --workers 1`
- Working dir: `backend/`, reads `backend/.env`, auto-restarts on crash (`Restart=always`)
- Runs on port **8001** (port 8000 is reserved for an older dev server / k.initqube.com)

### nginx

- `/etc/nginx/conf.d/vuptime.duckdns.org.conf` proxies `vuptime.duckdns.org` → `127.0.0.1:8001`
- SSE streaming is enabled: `proxy_buffering off`, `proxy_cache off`, long `proxy_read_timeout`
- Other reverse-proxied apps on this host: vcliproxyapi (8317), vforgejo (3000), vn8nv (5678), vopenclaw (9119), k.initqube.com (8000)

### Deploying the frontend

```bash
cd frontend
vercel --prod --yes
```

`NEXT_PUBLIC_API_URL` is baked in at build time from the **project env var** (`NEXT_PUBLIC_API_URL=https://vuptime.duckdns.org`, set for Production via `vercel env add NEXT_PUBLIC_API_URL production`). Do NOT pass `--build-env NEXT_PUBLIC_API_URL=...` — the CLI rejects it with "Not authorized". After any change to the env var, redeploy.

### Production caveats

- All API endpoints require a Bearer token (username/password login, default `admin`/`admin`); **no rate limiting** — acceptable for initial release, revisit later
- Repos are cloned to `~/.derive/u{user_id}/{owner}__{name}` on the host (not persisted in a volume) — it's the production host itself

## API Configuration

Chat and embeddings use **separate endpoints**:

| Purpose | Env Var | Default |
|---|---|---|
| Chat base URL | `OPENAI_API_BASE` | `https://vcliproxyapi.duckdns.org` |
| Chat API key | `OPENAI_API_KEY` | (required) |
| Chat model | `OPENAI_MODEL` | `deepseek-v4-flash-free` |
| Embedding base URL | `OPENAI_EMBEDDING_BASE` | `https://integrate.api.nvidia.com/v1` |
| Embedding API key | `OPENAI_EMBEDDING_API_KEY` | (required) |
| Embedding model | `OPENAI_EMBEDDING_MODEL` | `nvidia/nemotron-3-embed-1b` |

> **Note**: The embedding model produces 2048-dim vectors. pgvector's ivfflat/hnsw indexes cap at 2000 dims, so `code_embeddings` uses exact cosine search (no ANN index). This is performant for typical codebase sizes (<100k symbols).

## Step-by-Step Implementation Guides

Detailed, sequential implementation instructions live in `docs/steps/`:

| Guide | Covers | Status |
|---|---|---|
| `01-infrastructure.md` | Docker, deps, config, models, routers, migrations | **Done** |
| `02-tree-sitter-parsing.md` | `services/parser.py` — symbol extraction for 11 languages (Python, JS, TS, Rust, Go, Java, C, C++, C#, Ruby, PHP) | **Done** |
| `03-embeddings-and-indexing.md` | `services/embeddings.py` + `services/indexer.py` | **Done** |
| `04-semantic-search.md` | `services/search.py` — pgvector cosine similarity | **Done** |
| `05-rag-chat.md` | `services/rag.py` — retrieval + LLM streaming | **Done** |
| `06-frontend.md` | Dashboard, repo browser, code viewer, search, chat, GitHub OAuth | **Done** |
| `07-phase2-advanced.md` | Dependency graph, git diff analysis, doc generation | **Done** |

## Migrations

| Revision | Description |
|---|---|
| `454e27362b68` | Initial schema (repos, files, symbols, embeddings, chat) |
| `051b2df8478e` | Add dependencies + generated_docs tables |
| `ce78ab1e4c1c` | Change embedding dim 1536→2048, drop ivfflat index |

## Build & Run

### Database

```bash
docker compose up -d          # pgvector Postgres on :5432
docker compose exec db psql -U codebase -d codebase_intelligence -c "\dt"
```

### Backend (uv)

```bash
cd backend
cp ../.env.example .env       # fill in real values (API keys)
uv sync                       # Install deps into .venv (first time)
uv run alembic upgrade head   # Apply migrations
uv run python src/backend/main.py   # Run dev server on http://localhost:8001 (settings.port)
uv add <package>              # Add a dependency
```

> On the production host the backend runs as a systemd service (`codebase-intelligence`) on port **8001** — see "Production" above. Port 8000 belongs to an older dev server, do not use it.

### Frontend (bun)

```bash
cd frontend
bun install                   # Install deps
bun run dev                   # Dev server on http://localhost:3000
bun run build                 # Production build
bun run start                 # Serve production build
```

> **IMPORTANT**: Do NOT prefix Next.js scripts with `bun --bun` (e.g. `bun --bun next dev`). Bun 1.3.13's runtime segfaults running Next.js 16's Turbopack page-data collection. Bun is used only as the package manager; Next.js runs on the Node runtime.

## Project Layout

```
├── docker-compose.yml        # pgvector Postgres (port 5432)
├── .env.example              # env template — copy to .env / frontend/.env.local
├── docs/
│   └── steps/                # Step-by-step implementation guides (01-07)
├── backend/                  # Python API (uv)
│   ├── pyproject.toml        # uv project config + deps
│   ├── .python-version       # Python 3.13
│   ├── alembic/              # migrations (env.py is async)
│   ├── alembic.ini           # prepend_sys_path = . src
│   ├── repos/                # cloned repos (gitignored)
│   └── src/backend/
│       ├── main.py           # FastAPI app + router registration (9 routers)
│       ├── config.py         # pydantic-settings (reads .env, split chat/embedding config)
│       ├── db.py             # async engine/session/Base
│       ├── models/           # SQLAlchemy models (8 tables)
│       ├── schemas/          # Pydantic request/response models
│       ├── routers/          # repos, index, search, chat, files, auth, dependencies, diffs, docs
│       └── services/         # github, parser, embeddings, indexer, search, rag, diffs, docs
└── frontend/                 # Next.js app (bun)
    ├── src/
    │   ├── app/              # App Router pages (dashboard, repos/[id], login)
    │   ├── components/       # UI components (chat-panel, file-tree, code-viewer, search-bar,
    │   │                     #   dependency-graph, commit-list, generated-docs, repo-card, etc.)
    │   └── lib/api.ts        # Typed API client for all backend endpoints (authFetch, SSE parsing)
    └── package.json
```

## Chat-First UI

The AI chat is the **primary experience** of this app, not the code browser.

- On `repos/[id]`, `<ChatPanel>` fills the main center area and is always visible.
- The code browser (file tree, code viewer, graph, commits, README) lives in a slide-in right panel (`w-[55%]`, max 900px), **hidden by default**. It opens on demand:
  - The "Code" toggle button in the header
  - Selecting a search result
  - A URL `?file=`/`?line=` param
- Chat messages render **markdown** (ReactMarkdown + remark-gfm) with shiki-syntax-highlighted fenced code blocks. Code blocks inside chat messages use the `.chat-code-block` CSS class and must **not** include line numbers.
- Each AI reply shows **clickable source chips** under the message (one per retrieved symbol: `symbol_name · path/file.py:line`). Clicking a chip calls the `onOpenFile` prop → `navigateToFile()` in the repo page, opening the code panel scrolled to that function with a shareable `?file=`/`?line=` URL. Chips come from the RAG-retrieved context (`event: references`), not from parsing the LLM text — so they're always accurate. Chips survive session reloads via a `<!--refs:{json}-->` marker appended to the persisted assistant message.
- The repo page header keeps: back arrow, repo name/branch, semantic search bar, and the Code toggle. The old "Chat toggle" sidebar behavior no longer exists.

## Key Conventions

- **Python deps**: declare in `backend/pyproject.toml` via `uv add` — never pip-install directly
- **Node deps**: install with `bun add <package>` — never npm/pnpm
- **Python version**: pinned in `backend/.python-version` (3.13) — do not change
- **TypeScript**: strict, import alias `@/*` maps to `frontend/src/*`
- **Git**: monorepo with a single repo at the root; commit from the root
- **Database**: PostgreSQL + pgvector only (Docker Compose); use Alembic for all schema changes — never hand-edit tables
- **LLM chat**: OpenAI-compatible endpoint configured via `OPENAI_API_BASE`/`OPENAI_API_KEY` in `.env`
- **Embeddings**: separate NVIDIA endpoint via `OPENAI_EMBEDDING_BASE`/`OPENAI_EMBEDDING_API_KEY` — 2048-dim vectors, cosine distance (`<=>`) for search, no ANN index
- **Streaming**: chat responses stream via SSE (`text/event-stream`); each `data:` payload is **JSON-encoded** (`{"text": "..."}`), errors use `event: error`, completion uses `event: done`. Additionally `stream_rag_response` (`services/rag.py`) yields `("refs", {"references": [...], "marker": "..."})` first, forwarded by the router as `event: references` (`{"references": [...]}`) — the frontend (`lib/api.ts`) JSON-parses every event and `streamChat` takes an `onReferences` callback
- **CORS**: `FRONTEND_URL` in `.env` is a **comma-separated list** of allowed origins (e.g. `http://localhost:3000,https://codebase-intelligence-jet.vercel.app`)
- **Indexing runs as a FastAPI BackgroundTask** with its own DB session (`async_session`) — never reuse request-scoped sessions; the error handler calls `db.rollback()` before setting `status=error`
- **Embedding retries**: `services/embeddings.py` retries API calls with exponential backoff (5 attempts, batch size 50) to survive NVIDIA rate limits
- **Git operations**: `clone_repo` / `walk_source_files` run inside `asyncio.to_thread()` in the indexer — never call them directly from async code
- **Status enum**: `pending → cloning → indexing → ready` (or `error`), surfaced via `GET /api/repos/{id}/index/status`
- **Auth**: all API calls go through `authFetch` in `frontend/src/lib/api.ts` — it redirects to `/login` on any 401 (except on the login page itself). `AuthGuard` validates the token against the backend on mount before rendering children. Never use raw `fetch` for backend calls.
- **Frontend fetch**: `getToken()`/`setToken()`/`clearAuth()` manage the `auth_token` in `localStorage`; `authHeaders()` attaches the Bearer token. `login()`/`logout()` deliberately bypass `authFetch` since they manage auth state themselves.
