"""GitHub repository cloning and file listing service."""
from __future__ import annotations

import logging
from pathlib import Path

from git import Repo

from backend.config import settings

logger = logging.getLogger(__name__)

# File extensions we support for parsing
SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mjs": "javascript",
    ".mts": "typescript",
}

# Directories to skip
SKIP_DIRS = {
    "node_modules",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    ".next",
    "dist",
    "build",
    ".tox",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "vendor",
    ".idea",
    ".vscode",
}

# Max file size to index (500KB)
MAX_FILE_SIZE = 500 * 1024


def clone_repo(github_url: str, owner: str, name: str) -> Path:
    """Clone a GitHub repository to the local repos directory.

    Returns the path to the cloned repo.
    """
    repo_dir = settings.repos_path / f"{owner}__{name}"

    if repo_dir.exists():
        logger.info(f"Repo already exists at {repo_dir}, pulling latest...")
        repo = Repo(repo_dir)
        origin = repo.remotes.origin
        origin.pull()
        return repo_dir

    logger.info(f"Cloning {github_url} to {repo_dir}...")
    Repo.clone_from(
        f"{github_url}.git",
        str(repo_dir),
        depth=1,  # Shallow clone for speed
    )
    return repo_dir


def get_default_branch(repo_dir: Path) -> str:
    """Get the default branch of a cloned repo."""
    repo = Repo(repo_dir)
    try:
        return repo.active_branch.name
    except TypeError:
        return "main"


def walk_source_files(repo_dir: Path) -> list[dict]:
    """Walk the repo and return all supported source files.

    Returns a list of dicts with keys: path (relative), language, content.
    """
    files = []

    for file_path in repo_dir.rglob("*"):
        # Skip directories
        if file_path.is_dir():
            continue

        # Check if any parent dir should be skipped
        rel = file_path.relative_to(repo_dir)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue

        # Check extension
        ext = file_path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue

        # Check file size
        if file_path.stat().st_size > MAX_FILE_SIZE:
            logger.warning(f"Skipping {rel}: file too large")
            continue

        # Read content
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"Skipping {rel}: {e}")
            continue

        files.append({
            "path": str(rel),
            "language": SUPPORTED_EXTENSIONS[ext],
            "content": content,
        })

    logger.info(f"Found {len(files)} source files in {repo_dir}")
    return files
