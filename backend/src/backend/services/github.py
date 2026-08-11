"""GitHub repository cloning and file listing service."""
from __future__ import annotations

import logging
import uuid
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
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".phtml": "php",
}

# Binary / non-text extensions — never indexed (browsable tree only shows text files)
SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".zip", ".gz", ".tar", ".xz", ".bz2", ".7z", ".rar",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".pptx",
    ".mp3", ".mp4", ".wav", ".ogg", ".flac", ".webm",
    ".exe", ".dll", ".so", ".dylib", ".a", ".o", ".obj",
    ".class", ".jar", ".wasm", ".pyc", ".pyo",
    ".lock", ".woff2", ".map",
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


def repo_dir_for(user_id: uuid.UUID, owner: str, name: str) -> Path:
    """Per-user clone location: ~/.derive/u<user_id>/<owner>__<name>."""
    return settings.repos_path / f"u{user_id}" / f"{owner}__{name}"


def clone_repo(github_url: str, owner: str, name: str, user_id: uuid.UUID) -> Path:
    """Clone a GitHub repository to the user's repos directory.

    Always a shallow clone (--depth 1). Returns the path to the cloned repo.
    """
    repo_dir = repo_dir_for(user_id, owner, name)
    repo_dir.parent.mkdir(parents=True, exist_ok=True)

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
    """Walk the repo and return all text files.

    Files with a supported extension get their language (python/javascript/
    typescript/rust) so tree-sitter can parse them; everything else is stored
    with language "text" so the file tree and code viewer work for any file.

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
        if ext in SKIP_EXTENSIONS:
            continue

        # Check file size
        if file_path.stat().st_size > MAX_FILE_SIZE:
            logger.warning(f"Skipping {rel}: file too large")
            continue

        # Read content
        try:
            # Sniff for binary content before reading the whole file
            with open(file_path, "rb") as f:
                head = f.read(8192)
            if b"\x00" in head:
                logger.warning(f"Skipping {rel}: binary file")
                continue
            content = head.decode("utf-8", errors="replace")
            if file_path.stat().st_size > 8192:
                content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"Skipping {rel}: {e}")
            continue

        files.append({
            "path": str(rel),
            "language": SUPPORTED_EXTENSIONS.get(ext, "text"),
            "content": content,
        })

    logger.info(f"Found {len(files)} text files in {repo_dir}")
    return files
