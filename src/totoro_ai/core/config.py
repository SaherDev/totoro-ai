import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


def find_project_root() -> Path:
    """Walk up from this file until we find pyproject.toml."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    raise FileNotFoundError("Could not find project root (no pyproject.toml found)")


def load_yaml_config(name: str) -> dict[str, Any]:
    """Load a YAML config file.

    For .local.yaml: tries the file first (local dev), falls back to
    environment variables when the file is absent (Railway / production).
    For all other files (e.g. app.yaml): file must exist.
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
        f"Config not found at {config_path}. " "Check your working directory."
    )


def _config_from_env() -> dict[str, Any]:
    """Build .local.yaml config structure from environment variables.

    Used in production (Railway) where no YAML secrets file is present.
    Only covers secrets — non-secret config lives in committed app.yaml.
    """
    return {
        "database": {
            "url": os.environ["DATABASE_URL"],
        },
        "redis": {
            "url": os.environ.get("REDIS_URL", ""),
        },
        "providers": {
            "openai": {"api_key": os.environ.get("OPENAI_API_KEY")},
            "anthropic": {"api_key": os.environ.get("ANTHROPIC_API_KEY")},
            "voyage": {"api_key": os.environ.get("VOYAGE_API_KEY")},
            "google": {"api_key": os.environ.get("GOOGLE_API_KEY")},
        },
    }


# ---------------------------------------------------------------------------
# Typed config models (ADR-015, ADR-016, ADR-029)
# ---------------------------------------------------------------------------


class AppMeta(BaseModel):
    name: str
    description: str
    api_prefix: str


class LLMRoleConfig(BaseModel):
    provider: str
    model: str
    max_tokens: int = 1024
    temperature: float = 1.0


class ConfidenceWeights(BaseModel):
    base_scores: dict[str, float]
    places_modifiers: dict[str, float]
    multi_source_bonus: float = 0.10
    max_score: float = 0.95


class ExtractionThresholds(BaseModel):
    store_silently: float = 0.70
    require_confirmation: float = 0.30


class ExtractionConfig(BaseModel):
    confidence_weights: ConfidenceWeights
    thresholds: ExtractionThresholds


class AppConfig(BaseModel):
    app: AppMeta
    models: dict[str, LLMRoleConfig]
    extraction: ExtractionConfig


# Singleton — loaded once at first call, reused for the process lifetime.
_config: AppConfig | None = None


def get_config() -> AppConfig:
    """Return the app config singleton, loading app.yaml on first call."""
    global _config
    if _config is None:
        _config = AppConfig(**load_yaml_config("app.yaml"))
    return _config
