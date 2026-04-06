# Research: Extraction Cascade Run 2

## Resolved Decisions

### 1. `ExtractionPending` compatibility with `EventDispatcherProtocol`

**Decision**: Add `event_type: str = "extraction_pending"` as a dataclass field with a default to `ExtractionPending` in `types.py`.

**Rationale**: `EventDispatcher.dispatch()` does `self.handler_registry.get(event.event_type)`. `ExtractionPending` currently has no `event_type` attribute, so dispatching it would raise `AttributeError` at runtime and fail `mypy --strict`. Adding the field with a default value is a non-breaking additive change — all existing code that constructs `ExtractionPending` continues to work unchanged.

**Alternatives considered**:
- Wrap `ExtractionPending` in a `DomainEvent` shell at dispatch time — adds indirection with no benefit.
- Make `ExtractionPending` inherit from `DomainEvent` (Pydantic BaseModel) — can't mix Pydantic BaseModel inheritance with dataclasses cleanly; breaks the zero-dependency-on-events-module rule.

**Impact**: Minimal. `types.py` is listed as "not to be modified unless necessary" — this is necessary for the dispatch mechanism to work.

---

### 2. Vision Frames enricher: multimodal LLM API

**Decision**: `VisionFramesEnricher` reads the orchestrator model name from `get_config().models["orchestrator"].model` and creates an `anthropic.AsyncAnthropic` client directly (not via `get_llm()`). The model name is never hardcoded — it comes from config.

**Rationale**: The current `LLMClientProtocol` only supports text-based `complete(messages: list[dict[str, str]])`. Anthropic vision calls require structured content blocks with `type: "image"` and `type: "text"` — a different message schema. The protocol cannot carry this without a breaking change. Since extending `LLMClientProtocol` for vision is deferred to a future run, the enricher resolves the model name from config (satisfying the spirit of ADR-020) and calls the Anthropic SDK directly.

**Alternatives considered**:
- Extend `LLMClientProtocol` with a `complete_with_images(...)` method in Run 2 — added scope not required by this run's spec.
- Pass in a pre-constructed `anthropic.AsyncAnthropic` instance via constructor — acceptable, and preferred for testability. Constructor takes `anthropic.AsyncAnthropic` + model name string (read from config at wiring time).

**ADR-020 compliance note**: Spirit preserved — model name comes from config, not hardcoded. Full protocol compliance deferred to Run 3 when a vision method can be added to `LLMClientProtocol`.

**Complexity Tracking entry**: Required in `plan.md`.

---

### 3. Groq Whisper API integration

**Decision**: `GroqWhisperClient` uses the `groq` Python SDK (`pip install groq`). The SDK provides `AsyncGroq` with an OpenAI-compatible interface. Audio transcription calls `client.audio.transcriptions.create(model="whisper-large-v3", ...)`.

**Rationale**: The Groq SDK is the canonical integration path. It supports both URL-based (pass `url=cdn_url`) and file-based (pass `file=BytesIO(audio_bytes)`) transcription in a single API call.

**Alternatives considered**:
- Use `httpx` directly against Groq's REST API — more code, same result.
- Use OpenAI SDK with Groq's base URL — works but using the dedicated SDK is cleaner.

**Secrets**: Groq API key needs to be added to `SecretsConfig` under `providers.groq.api_key` and to `config/.local.yaml`. **Note**: `SecretsConfig` must be updated to add a `groq` provider entry (this is a modification to `core/config.py`).

---

### 4. `SubtitleCheckEnricher` NER approach

**Decision**: `SubtitleCheckEnricher` accepts an `InstructorClient` via constructor and replicates the NER logic from `LLMNEREnricher` with `source=ExtractionLevel.SUBTITLE_CHECK`. The import restriction is `extractors/` (the existing pre-cascade extractors), not `enrichers/` — so importing `LLMNEREnricher` is technically allowed. However, `LLMNEREnricher.enrich()` hardcodes `ExtractionLevel.LLM_NER`. To avoid rewriting context state, the enricher has its own `_extract_places(text) -> list[CandidatePlace]` helper that mirrors the LLM NER prompt but uses `ExtractionLevel.SUBTITLE_CHECK`.

**Rationale**: DRY matters but not at the cost of coupling enrichers to each other. Each enricher must produce candidates with its own `ExtractionLevel` source — sharing the NER helper function would require parameterising the source, making `LLMNEREnricher` more complex than its single-responsibility warrants.

---

### 5. `asyncio.gather` with `return_exceptions=True` in `GooglePlacesValidator`

**Decision**: `validate()` calls `await asyncio.gather(*coros, return_exceptions=True)`. The result list may contain `BaseException` instances. These are filtered out alongside `None` results. Only `ExtractionResult` instances are kept.

**Rationale**: This is the explicit requirement from the spec and the correct way to prevent one failure from aborting the batch. `return_exceptions=True` is preferred over per-candidate try/except because it lets all candidates complete before any filtering occurs.

---

### 6. Dedup ordering by `ExtractionLevel` enum index

**Decision**: `dedup_candidates` uses `list(ExtractionLevel).index(candidate.source)` to determine priority. Lower index = higher priority. The enum is ordered: `EMOJI_REGEX=0`, `LLM_NER=1`, `SUBTITLE_CHECK=2`, `WHISPER_AUDIO=3`, `VISION_FRAMES=4`.

**Rationale**: Enum member ordering is stable in Python 3.11 and defined in `types.py`. Encoding priority as enum declaration order (not an explicit integer) avoids a secondary mapping that could drift out of sync.

---

### 7. `SecretsConfig` modification for Groq

**Decision**: Add `groq: ProviderKey = ProviderKey()` to `ProvidersConfig` in `core/config.py`, and add `GROQ_API_KEY` to `_EnvSource`. `GroqWhisperClient.__init__` takes `api_key: str` injected from `get_secrets().providers.groq.api_key`.

**Impact**: `core/config.py` needs one additive line to `ProvidersConfig` and one to `_EnvSource`. This is the correct pattern per ADR-029 (all provider keys in `SecretsConfig`).

---

### 8. `VTT subtitle stripping`

**Decision**: Strip VTT timing markers using regex: remove all lines matching `\d{2}:\d{2}:\d{2}\.\d{3} --> .*`, `WEBVTT`, `NOTE`, blank lines, and position/align cue settings. The remaining lines form the clean transcript text.

**Rationale**: VTT format is well-specified. A simple regex is sufficient and avoids a VTT parsing library dependency.

---

### 9. `ExtractionPipeline.run` signature

**Decision**: `run(url: str | None, user_id: str, supplementary_text: str = "") -> list[ExtractionResult] | ProvisionalResponse`

**Rationale**: Matches the spec exactly. `url=None` triggers plain-text-only paths (subtitle, audio, and vision enrichers skip).
