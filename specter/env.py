"""Finds and loads the .env file.

Lookup order: the repo's own folder first, then the folder one level above it.
Values already set in the process environment are never overwritten.
"""

from pathlib import Path

from dotenv import load_dotenv

REPO_DIR = Path(__file__).resolve().parent.parent
ENV_CANDIDATES = (REPO_DIR / ".env", REPO_DIR.parent / ".env")

_loaded_from: Path | None = None


def load_env() -> Path | None:
    """Load the first .env that exists. Returns its path, or None if neither exists."""
    global _loaded_from
    for path in ENV_CANDIDATES:
        if path.is_file():
            load_dotenv(path, override=False)
            _loaded_from = path
            return path
    return None


def env_source() -> str:
    """Which .env was used, described without revealing any values."""
    if _loaded_from is None:
        return "no .env file found (using process environment only)"
    where = "repo folder" if _loaded_from.parent == REPO_DIR else "parent folder"
    return f"{_loaded_from} ({where})"
