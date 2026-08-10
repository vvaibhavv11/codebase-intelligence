"""Embedding generation service using OpenAI-compatible API."""
from __future__ import annotations

import asyncio
import logging

from openai import AsyncOpenAI

from backend.config import settings

logger = logging.getLogger(__name__)

# ~6000 tokens, safe margin under typical embedding model token limits
MAX_EMBED_CHARS = 24_000

# Retry configuration
MAX_RETRIES = 5
RETRY_BASE_DELAY = 1.0  # seconds


def get_openai_client() -> AsyncOpenAI:
    """Return an async OpenAI client for chat/completions (vcliproxy)."""
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=_normalize_base(settings.openai_api_base),
    )


def _normalize_base(base_url: str) -> str:
    """Ensure the base URL ends with /v1 so the OpenAI client hits
    {base}/chat/completions instead of {base}/chat/completions 404ing."""
    base_url = base_url.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url += "/v1"
    return base_url


def get_embedding_client() -> AsyncOpenAI:
    """Return an async OpenAI client for embeddings (NVIDIA endpoint)."""
    return AsyncOpenAI(
        api_key=settings.openai_embedding_api_key,
        base_url=settings.openai_embedding_base,
    )


def truncate_for_embedding(text: str) -> str:
    """Truncate text that exceeds the embedding model's token limit."""
    if len(text) <= MAX_EMBED_CHARS:
        return text
    return text[:MAX_EMBED_CHARS] + "\n... [truncated]"


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


async def get_embedding(text: str) -> list[float]:
    """Generate embedding for a single text string."""
    client = get_embedding_client()
    for attempt in range(MAX_RETRIES):
        try:
            response = await client.embeddings.create(
                model=settings.openai_embedding_model,
                input=text,
                extra_body={"input_type": "query", "encoding_format": "float"},
            )
            return response.data[0].embedding
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                raise
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(
                "Embedding request failed (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1, MAX_RETRIES, delay, e,
            )
            await asyncio.sleep(delay)
    raise RuntimeError("Unreachable")


async def get_embeddings_batch(
    texts: list[str], batch_size: int = 50
) -> list[list[float]]:
    """Generate embeddings for multiple texts in batches."""
    client = get_embedding_client()
    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.embeddings.create(
                    model=settings.openai_embedding_model,
                    input=batch,
                    extra_body={"input_type": "passage", "encoding_format": "float"},
                )
                # Sort by index to maintain order
                sorted_data = sorted(response.data, key=lambda x: x.index)
                all_embeddings.extend([d.embedding for d in sorted_data])
                break
            except Exception as e:
                if attempt == MAX_RETRIES - 1:
                    raise
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Embedding batch %d failed (attempt %d/%d), retrying in %.1fs: %s",
                    i // batch_size, attempt + 1, MAX_RETRIES, delay, e,
                )
                await asyncio.sleep(delay)

    return all_embeddings
