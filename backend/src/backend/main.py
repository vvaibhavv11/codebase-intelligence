from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from backend.config import settings
from backend.db import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure pgvector extension exists
    from sqlalchemy.ext.asyncio import create_async_engine as _  # noqa: F401
    from backend.db import engine

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    await seed_default_user()

    yield

    # Shutdown
    await engine.dispose()


async def seed_default_user() -> None:
    """Ensure the default admin user exists (admin / admin)."""
    from sqlalchemy import select

    from backend.db import async_session
    from backend.models.user import User
    from backend.services.auth import hash_password

    async with async_session() as db:
        result = await db.execute(select(User).where(User.username == "admin"))
        if result.scalar_one_or_none():
            return
        db.add(User(username="admin", password_hash=hash_password("admin")))
        await db.commit()


app = FastAPI(
    title="Codebase Intelligence API",
    description="Analyze, search, and chat about code repositories",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.frontend_url.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and register routers
from backend.routers import repos, index, search, chat, files, auth  # noqa: E402
from backend.routers import dependencies, diffs, docs  # noqa: E402

app.include_router(repos.router, prefix="/api")
app.include_router(index.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(dependencies.router, prefix="/api")
app.include_router(diffs.router, prefix="/api")
app.include_router(docs.router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=True,
    )
