"""Central config module — single source of truth for all app configuration.

Two singletons:
- get_config()   → AppConfig    from config/app.yaml (committed, non-secret)
- get_secrets()  → SecretsConfig from .env → env vars (never committed)

All other modules import from here. Nobody calls load_yaml_config() directly.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

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


class ConfidenceConfig(BaseModel):
    """Per-level confidence scoring config (ADR-029, ADR-057).

    base_scores keys are ExtractionLevel.value strings (e.g. "emoji_regex").
    max_score caps the output — no extraction path earns 1.0.

    Two-band save gate (ADR-057):
      confidence <  save_threshold      → not written, surfaces as "failed".
      save_threshold ≤ c < confident    → written with status "needs_review".
      confidence ≥  confident_threshold → written silently as "saved".
    """

    base_scores: dict[str, float] = {
        "emoji_regex": 0.95,
        "llm_ner": 0.60,
        "subtitle_check": 0.75,
        "whisper_audio": 0.65,
        "vision_frames": 0.55,
    }
    signal_scores: dict[str, float] = {
        "emoji_marker": 0.92,
        "location_tag": 0.85,
        "caption": 0.75,
        "hashtag": 0.55,
    }
    corroboration_bonus: float = 0.10
    max_score: float = 0.97
    save_threshold: float = 0.30
    confident_threshold: float = 0.70


class ExtractionThresholds(BaseModel):
    store_silently: float = 0.70
    require_confirmation: float = 0.30


class ExtractionVisionConfig(BaseModel):
    max_frames: int = 5
    scene_threshold: float = 0.3
    timeout_seconds: float = 10.0


class ExtractionWhisperConfig(BaseModel):
    timeout_seconds: float = 8.0
    audio_format: str = "opus"
    audio_quality: str = "32k"


class ExtractionSubtitleConfig(BaseModel):
    output_dir: str = "/tmp/subtitles"
    format: str = "vtt"


class ExtractionConfig(BaseModel):
    confidence_weights: ConfidenceWeights
    thresholds: ExtractionThresholds
    mutable_fields: list[str] = [
        "place_name",
        "address",
        "cuisine",
        "price_range",
        "lat",
        "lng",
        "source_url",
        "validated_at",
        "confidence",
        "source",
    ]
    confidence: ConfidenceConfig = ConfidenceConfig()
    circuit_breaker_threshold: int = 5
    circuit_breaker_cooldown: float = 900.0
    vision: ExtractionVisionConfig = ExtractionVisionConfig()
    whisper: ExtractionWhisperConfig = ExtractionWhisperConfig()
    subtitle: ExtractionSubtitleConfig = ExtractionSubtitleConfig()


class ExternalServiceConfig(BaseModel):
    base_url: str
    timeout_seconds: float


class GooglePlacesConfig(ExternalServiceConfig):
    nearbysearch_url: str = (
        "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    )
    request_fields: list[str] = ["name", "formatted_address", "place_id", "geometry"]
    default_region: str = "th"


class ExternalServicesConfig(BaseModel):
    google_places: GooglePlacesConfig = GooglePlacesConfig(
        base_url="https://maps.googleapis.com/maps/api/place/findplacefromtext/json",
        timeout_seconds=5.0,
    )
    tiktok_oembed: ExternalServiceConfig = ExternalServiceConfig(
        base_url="https://www.tiktok.com/oembed", timeout_seconds=3.0
    )


class EmbeddingsConfig(BaseModel):
    """Embedding configuration (ADR-054).

    `description_fields` drives the order and inclusion of `PlaceObject`
    Tier 1 fields in the embedding input. The persistence layer walks this
    list and emits each available value separated by
    `description_separator`. Retrieval evals can re-tune field order and
    inclusion by editing the config and re-embedding — no code change.
    """

    dimensions: int = 1024
    description_separator: str = " | "
    description_fields: list[str] = [
        "place_name",
        "subcategory",
        "place_type",
        "cuisine",
        "ambiance",
        "price_hint",
        "tags",
        "good_for",
        "dietary",
        "neighborhood",
        "city",
        "country",
    ]


class SystemPromptsConfig(BaseModel):
    consult: str = (
        "You are Totoro, an AI place recommendation assistant. "
        "Answer the user's query helpfully and concisely."
    )


class ConsultConfig(BaseModel):
    max_alternatives: int = 2
    placeholder_photo_url: str = "https://placehold.co/800x450.webp"
    response_timeout_seconds: int = 10
    default_radius_m: int = 1500
    nearby_radius_m: int = 500
    walking_radius_m: int = 1000


class RecallConfig(BaseModel):
    max_results: int = 10
    rrf_k: int = 60
    candidate_multiplier: int = 2
    min_rrf_score: float = 0.01
    max_cosine_distance: float = 0.65


class TasteModelEmaConfig(BaseModel):
    """EMA decay rates per dimension"""

    price_comfort: float
    dietary_alignment: float
    cuisine_frequency: float
    ambiance_preference: float
    crowd_tolerance: float
    cuisine_adventurousness: float
    time_of_day_preference: float
    distance_tolerance: float


class TasteModelSignalsConfig(BaseModel):
    """Signal gain values per interaction type"""

    save: float
    accepted: float
    rejected: float
    onboarding_explicit_positive: float
    onboarding_explicit_negative: float
    ignored: float
    repeat_visit: float
    search_accepted: float


class TasteModelObservationsConfig(BaseModel):
    """Observation value lookup tables per dimension"""

    price_comfort: dict[str, float] = {}
    dietary_alignment: dict[str, float] = {}
    cuisine_frequency: dict[str, float] = {}
    ambiance_preference: dict[str, float] = {}
    crowd_tolerance: dict[str, float] = {}
    cuisine_adventurousness: dict[str, float] = {}
    time_of_day_preference: dict[str, float] = {}
    distance_tolerance: dict[str, float] = {}


class TasteModelConfig(BaseModel):
    """Taste model configuration"""

    ema: TasteModelEmaConfig
    signals: TasteModelSignalsConfig
    observations: TasteModelObservationsConfig = TasteModelObservationsConfig()


class RankingWeightsConfig(BaseModel):
    """Ranking score weights"""

    taste_similarity: float
    distance: float
    price_fit: float
    popularity: float
    source_boost: float = 0.15


class RankingConfig(BaseModel):
    """Ranking configuration"""

    weights: RankingWeightsConfig


class MemoryConfidenceConfig(BaseModel):
    """Personal fact confidence thresholds."""

    stated: float = 0.9
    inferred: float = 0.6


class MemoryConfig(BaseModel):
    """User memory layer configuration."""

    confidence: MemoryConfidenceConfig = MemoryConfidenceConfig()


class ProviderEndpointConfig(BaseModel):
    """Non-secret provider config (base URL, etc.). API keys live in SecretsConfig."""

    base_url: str


class AppProvidersConfig(BaseModel):
    """Non-secret provider endpoints (base URLs). API keys live in SecretsConfig."""

    groq: ProviderEndpointConfig = ProviderEndpointConfig(
        base_url="https://api.groq.com"
    )
    ollama: ProviderEndpointConfig = ProviderEndpointConfig(
        base_url="http://localhost:11434/v1"
    )


class PlacesConfig(BaseModel):
    """PlacesService cache TTL and per-request fetch cap (ADR-054, feature 019).

    - cache_ttl_days: single lifetime for both the Tier 2 geo cache and the
      Tier 3 enrichment cache. Both set_batch methods in PlacesCache use
      `cache_ttl_days * 86400` seconds. Default 30 days.
    - max_enrichment_batch: per-request cap on external provider fetches
      in PlacesService.enrich_batch(geo_only=False). Counts unique provider_id,
      not input positions.
    """

    cache_ttl_days: int = 30
    max_enrichment_batch: int = 10


class AppConfig(BaseModel):
    app: AppMeta
    models: dict[str, LLMRoleConfig]
    extraction: ExtractionConfig
    providers: AppProvidersConfig = AppProvidersConfig()
    external_services: ExternalServicesConfig = ExternalServicesConfig()
    embeddings: EmbeddingsConfig = EmbeddingsConfig()
    system_prompts: SystemPromptsConfig = SystemPromptsConfig()
    consult: ConsultConfig = ConsultConfig()
    recall: RecallConfig = RecallConfig()
    taste_model: TasteModelConfig
    ranking: RankingConfig
    memory: MemoryConfig = MemoryConfig()
    places: PlacesConfig = PlacesConfig()


_config: AppConfig | None = None


def get_config() -> AppConfig:
    """Return the AppConfig singleton, loading app.yaml on first call."""
    global _config
    if _config is None:
        _config = AppConfig(**load_yaml_config("app.yaml"))
    return _config


# ---------------------------------------------------------------------------
# SecretsConfig — flat secrets from .env or environment variables
# ---------------------------------------------------------------------------

_ENV_FILE = find_project_root() / ".env"


class SecretsConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str
    REDIS_URL: str = ""
    OPENAI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    VOYAGE_API_KEY: str | None = None
    GOOGLE_API_KEY: str | None = None
    GROQ_API_KEY: str | None = None
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_SECRET_KEY: str | None = None
    LANGFUSE_HOST: str | None = None


_secrets: SecretsConfig | None = None


def get_secrets() -> SecretsConfig:
    """Return the SecretsConfig singleton.

    Reads from .env (local dev) and environment variables (Railway).
    Environment variables take precedence over .env values.
    """
    global _secrets
    if _secrets is None:
        _secrets = SecretsConfig()
    return _secrets
