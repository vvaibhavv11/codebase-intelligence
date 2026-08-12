"""Semantic search service using pgvector cosine similarity."""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.embedding import CodeEmbedding
from backend.models.symbol import CodeSymbol
from backend.schemas.search import SearchResult
from backend.services.embeddings import get_embedding

logger = logging.getLogger(__name__)

# Results with cosine similarity below this threshold are filtered out.
# Nemotron embeddings score relevant matches ~0.35-0.45 and loose but
# useful matches ~0.15-0.3; the noise floor is ~0.06-0.1.
MIN_SIMILARITY = 0.15


def _truncate_source(source: str, max_lines: int = 15) -> str:
    """Truncate source code to a preview for search results."""
    lines = source.split("\n")
    if len(lines) <= max_lines:
        return source
    return "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"


async def search_code(
    db: AsyncSession,
    repo_id: uuid.UUID,
    query: str,
    limit: int = 20,
) -> list[SearchResult]:
    """Perform semantic search over indexed code symbols.

    1. Embed the user's query using the same model used for indexing.
    2. Run a pgvector cosine-distance query against ``code_embeddings``
       filtered by *repo_id* and joined with ``code_symbols``.
    3. Return ranked results with similarity scores.
    """
    # Step 1: Embed the query text
    query_embedding = await get_embedding(query)

    # Step 2: Build the vector similarity query
    distance = CodeEmbedding.embedding.cosine_distance(query_embedding)

    stmt = (
        select(
            CodeEmbedding,
            CodeSymbol,
            distance.label("distance"),
        )
        .join(CodeSymbol, CodeEmbedding.symbol_id == CodeSymbol.id)
        .where(CodeEmbedding.repo_id == repo_id)
        .where(distance < (1 - MIN_SIMILARITY))  # filter low-relevance results
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
            score=round(1 - dist, 4),
        )
        for embedding, symbol, dist in rows
    ]
