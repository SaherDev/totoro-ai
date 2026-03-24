"""Central config module — single source of truth for all app configuration.

Two singletons:
- get_config()   → AppConfig    from config/app.yaml (committed, non-secret)
- get_secrets()  → SecretsConfig from config/.local.yaml → env vars (never committed)

All other modules import from here. Nobody calls load_yaml_config() directly.
"""

import os
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Low-level YAML loader (internal — use get_config / get_secrets instead)
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
    """Load a YAML config file from config/<name>. File must exist."""
    config_path = find_project_root() / "config" / name
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config not found at {config_path}. Check your working directory."
        )
    try:
        with config_path.open() as f:
            result = yaml.safe_load(f)
    except yaml.YAMLError as err:
        raise ValueError(f"Invalid YAML in {config_path}: {err}") from err
    if not isinstance(result, dict):
        raise ValueError(
            f"Expected a YAML mapping in {config_path}, got {type(result).__name__}"
        )
    return result


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


# ---------------------------------------------------------------------------
# Secrets sources — tried in order by get_secrets()
# ---------------------------------------------------------------------------


class _SecretsSource(Protocol):
    def load(self) -> dict[str, Any] | None: ...


class _YamlFileSource:
    """Load secrets from config/.local.yaml (local dev)."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict[str, Any] | None:
        """Return parsed YAML dict, or None if file does not exist."""
        if not self._path.exists():
            return None
        try:
            with self._path.open() as f:
                result = yaml.safe_load(f)
        except yaml.YAMLError as err:
            raise ValueError(f"Invalid YAML in {self._path}: {err}") from err
        if not isinstance(result, dict):
            raise ValueError(
                f"Expected a YAML mapping in {self._path}, got {type(result).__name__}"
            )
        return result


class _EnvSource:
    """Load secrets from environment variables (Railway production)."""

    def load(self) -> dict[str, Any]:
        """Return secrets dict from env vars. DATABASE_URL is required."""
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise ValueError(
                "DATABASE_URL environment variable is required but not set. "
                "In local dev, create config/.local.yaml instead."
            )
        return {
            "database": {"url": url},
            "redis": {"url": os.environ.get("REDIS_URL", "")},
            "providers": {
                "openai": {"api_key": os.environ.get("OPENAI_API_KEY")},
                "anthropic": {"api_key": os.environ.get("ANTHROPIC_API_KEY")},
                "voyage": {"api_key": os.environ.get("VOYAGE_API_KEY")},
                "google": {"api_key": os.environ.get("GOOGLE_API_KEY")},
            },
        }


_secrets: SecretsConfig | None = None


def get_secrets() -> SecretsConfig:
    """Return the SecretsConfig singleton.

    Sources tried in order:
    1. config/.local.yaml  (local dev)
    2. Environment variables (Railway production)
    """
    global _secrets
    if _secrets is None:
        sources: list[_SecretsSource] = [
            _YamlFileSource(find_project_root() / "config" / ".local.yaml"),
            _EnvSource(),
        ]
        raw = next((r for s in sources if (r := s.load()) is not None), None)
        if raw is None:
            raise ValueError("No secrets source returned a configuration")
        _secrets = SecretsConfig(**raw)
    return _secrets
