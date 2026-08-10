# TODO — Remaining Work

## 1. End-to-End Testing (HIGH priority)

All code is written but has never been run against a real repo. This is the critical next step.

- [ ] Start backend: `cd backend && uv run python src/backend/main.py`
- [ ] Start frontend: `cd frontend && bun run dev`
- [ ] Connect a small GitHub repo via `POST /api/repos` (e.g. a small Python or JS project)
- [ ] Trigger indexing via `POST /api/repos/{id}/index`
- [ ] Monitor status via `GET /api/repos/{id}/index/status` until `ready`
- [ ] Verify file tree: `GET /api/files/{repo_id}/tree`
- [ ] Verify file content: `GET /api/files/{repo_id}/content?path=...`
- [ ] Verify semantic search: `GET /api/search?q=...&repo_id=...`
- [ ] Verify chat (SSE): `POST /api/chat` with a question about the indexed repo
- [ ] Verify dependency graph: `GET /api/dependencies/{repo_id}/graph`
- [ ] Verify commit list: `GET /api/diffs/{repo_id}/commits`
- [ ] Verify diff analysis (SSE): `POST /api/diffs/{repo_id}/analyze`
- [ ] Verify doc generation: `POST /api/docs/{repo_id}/symbol/{symbol_id}`
- [ ] Verify repo README generation: `POST /api/docs/{repo_id}/readme`
- [ ] Open frontend in browser and verify all tabs (Files, Graph, Commits, README) render data

> Note: production deployment is live (see AGENTS.md "Production"). Basic smoke tests passed:
> `GET /api/health`, CORS preflight from the Vercel origin, and the frontend loads.
> Full indexing/search/chat flow against a real repo is still unverified.

## 2. Bug Fixes & Edge Cases (partially done)

Fixes already shipped to production (Aug 2026):

- [x] SSE streaming robustness — chunks are JSON-encoded (`{"text": "..."}`), `event: error` on failures, `event: done` at end (routers/chat.py, routers/diffs.py, frontend lib/api.ts)
- [x] Indexer error handling — `db.rollback()` before setting `status=error`; git ops (`clone_repo`, `walk_source_files`) run in `asyncio.to_thread()`
- [x] Embedding API resilience — exponential backoff retries (5 attempts, batch size 50) for NVIDIA rate limits
- [x] `.env.example` — split chat/embedding config documented

Still TODO:

- [ ] Fix any import/runtime errors when indexing actually runs
- [ ] Fix any SSE streaming issues discovered in real browser testing
- [ ] Fix any frontend rendering issues with real data
- [ ] Handle repos with no symbols (empty or non-code repos) — currently silently becomes `ready` with 0 files; consider a user-facing warning
- [ ] Handle indexing failures gracefully (set status to `error` with message) — core path done, verify in practice

## 3. `.env.example` Update

- [x] Split chat/embedding config documented:
  - `OPENAI_EMBEDDING_BASE=https://integrate.api.nvidia.com/v1`
  - `OPENAI_EMBEDDING_API_KEY=`
  - `OPENAI_EMBEDDING_MODEL=nvidia/nemotron-3-embed-1b`

## 4. GitHub OAuth (LOW priority)

- [ ] Register a GitHub OAuth App and fill in `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` in `.env`
- [ ] Test the full OAuth flow: login page → GitHub redirect → callback → session
- [ ] Currently the app works without auth (all endpoints are unauthenticated)

## 5. Production Deployment (DONE — live Aug 2026)

- [x] Frontend deployed on Vercel: `https://codebase-intelligence-jet.vercel.app` (project `codebase-intelligence`)
- [x] Backend runs as systemd service `codebase-intelligence` on port **8001**
- [x] Reverse proxy: nginx `vuptime.duckdns.org` → `127.0.0.1:8001` (SSE buffering disabled)
- [x] CORS configured for production domain (comma-separated `FRONTEND_URL` in `backend/.env`)
- [x] Real `SECRET_KEY` set in `backend/.env`
- [x] SSL/TLS via existing Let's Encrypt cert on `vuptime.duckdns.org`
- [x] `uv.lock` now committed for deterministic builds
- [ ] Rate limiting on embedding/chat endpoints (NVIDIA free tier limits) — not yet implemented
- [ ] Authentication on API endpoints — not yet implemented
- [ ] DB credentials are still dev defaults (`codebase/codebase`) — harden if DB is ever exposed beyond localhost

## 6. Nice-to-Haves (FUTURE)

- [ ] Re-indexing support (detect changed files only, skip unchanged)
- [ ] Webhook-based auto-reindex on push
- [ ] Multi-language support beyond Python/JS/TS (Go, Rust, Java, etc.)
- [ ] Export dependency graph as SVG/PNG
- [ ] Persistent chat sessions across browser reloads
- [ ] User-scoped repos (requires OAuth to be set up)
- [ ] Repo deletion cleanup (remove cloned files + all DB records)

## Architecture Notes

- **Chat LLM**: `vcliproxyapi.duckdns.org` → `deepseek-v4-flash-free` (used by rag.py, diffs.py, docs.py)
- **Embeddings**: `integrate.api.nvidia.com/v1` → `nvidia/nemotron-3-embed-1b` (2048 dims, used by embeddings.py)
- **Vector search**: exact cosine distance (no ANN index — pgvector caps ivfflat/hnsw at 2000 dims, our vectors are 2048)
- **Migrations**: 3 applied (`454e27362b68` → `051b2df8478e` → `ce78ab1e4c1c`); `alembic/env.py` reads `DATABASE_URL` from env
