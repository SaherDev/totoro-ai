import os
from pathlib import Path
from typing import Any

import yaml


def find_project_root() -> Path:
    """Walk up from this file until we find pyproject.toml."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    raise FileNotFoundError(
        "Could not find project root (no pyproject.toml found)"
    )


def load_yaml_config(name: str) -> dict[str, Any]:
    """Load a YAML config file.

    For .local.yaml: tries the file first (local dev), falls back to
    environment variables when the file is absent (Railway / production).
    For all other files (e.g. models.yaml): file must exist.
    """
    config_path = find_project_root() / "config" / name
    if config_path.exists():
        try:
            with config_path.open() as f:
                result: dict[str, Any] = yaml.safe_load(f)
                return result
        except yaml.YAMLError as err:
            raise ValueError(f"Invalid YAML in {config_path}: {err}") from err

    if name == ".local.yaml":
        return _config_from_env()

    raise FileNotFoundError(
        f"Config not found at {config_path}. "
        "Check your working directory."
    )


def _config_from_env() -> dict[str, Any]:
    """Build .local.yaml config structure from environment variables.

    Used in production (Railway) where no YAML secrets file is present.
    """
    return {
        "app": {
            "name": os.environ.get("APP_NAME", "totoro-ai"),
            "description": os.environ.get("APP_DESCRIPTION", "AI engine for Totoro"),
            "api_prefix": os.environ.get("APP_API_PREFIX", "/v1"),
        },
        "database": {
            "url": os.environ["DATABASE_URL"],
        },
        "redis": {
            "url": os.environ.get("REDIS_URL", ""),
        },
        "providers": {
            "openai":    {"api_key": os.environ.get("OPENAI_API_KEY")},
            "anthropic": {"api_key": os.environ.get("ANTHROPIC_API_KEY")},
            "voyage":    {"api_key": os.environ.get("VOYAGE_API_KEY")},
            "google":    {"api_key": os.environ.get("GOOGLE_API_KEY")},
        },
    }
