"""Central config module — single source of truth for all app configuration.

Two singletons:
- get_config()   → AppConfig   from config/app.yaml (committed, non-secret)
- get_secrets()  → SecretsConfig from config/.local.yaml or env vars (never committed)

All other modules import from here. Nobody calls load_yaml_config() directly.
"""

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Low-level loader (internal — use get_config / get_secrets instead)
# ---------------------------------------------------------------------------


def find_project_root() -> Path:
    """Walk up from this file until we find pyproject.toml."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    raise FileNotFoundError("Could not find project root (no pyproject.toml found)")


def load_yaml_config(name: str) -> dict[str, Any]:
    """Load a YAML config file from config/<name>.

    For .local.yaml: falls back to environment variables when file is absent.
    For all other files: file must exist.
    """
    config_path = find_project_root() / "config" / name
    if config_path.exists():
        try:
            with config_path.open() as f:
                result = yaml.safe_load(f)
        except yaml.YAMLError as err:
            raise ValueError(f"Invalid YAML in {config_path}: {err}") from err
        if not isinstance(result, dict):
            raise ValueError(f"Expected a YAML mapping in {config_path}, got {type(result).__name__}")
        return result

    if name == ".local.yaml":
        return _secrets_from_env()

    raise FileNotFoundError(
        f"Config not found at {config_path}. Check your working directory."
    )


def _secrets_from_env() -> dict[str, Any]:
    """Build SecretsConfig-compatible dict from environment variables.

    Used in production (Railway) where config/.local.yaml is not present.
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
# AppConfig — non-secret config from config/app.yaml
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


_config: AppConfig | None = None


def get_config() -> AppConfig:
    """Return the AppConfig singleton, loading app.yaml on first call."""
    global _config
    if _config is None:
        _config = AppConfig(**load_yaml_config("app.yaml"))
    return _config


# ---------------------------------------------------------------------------
# SecretsConfig — secrets from config/.local.yaml or environment variables
# ---------------------------------------------------------------------------


class ProviderKey(BaseModel):
    api_key: str | None = None


class ProvidersConfig(BaseModel):
    openai: ProviderKey = ProviderKey()
    anthropic: ProviderKey = ProviderKey()
    voyage: ProviderKey = ProviderKey()
    google: ProviderKey = ProviderKey()


class DatabaseConfig(BaseModel):
    url: str


class RedisConfig(BaseModel):
    url: str = ""


class SecretsConfig(BaseModel):
    database: DatabaseConfig
    redis: RedisConfig = RedisConfig()
    providers: ProvidersConfig = ProvidersConfig()


_secrets: SecretsConfig | None = None


def get_secrets() -> SecretsConfig:
    """Return the SecretsConfig singleton, loading .local.yaml (or env vars) on first call."""
    global _secrets
    if _secrets is None:
        _secrets = SecretsConfig(**load_yaml_config(".local.yaml"))
    return _secrets
