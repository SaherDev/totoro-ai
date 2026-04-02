# Extraction Cascade — Integration Points

12 gaps between the new cascade design and the existing codebase/ADRs.

---

## 1. Pydantic, not dataclasses

Shared types (`CandidatePlace`, `ExtractionResult`, `ExtractionContext`, `ProvisionalResponse`, etc.) use `@dataclass`. Project standard requires `BaseModel` for all types crossing module boundaries (CLAUDE.md, architecture.md).

**Fix:** Convert all shared types to Pydantic `BaseModel`.

---

## 2. API response contract broken

Existing contract (`ExtractPlaceResponse`) returns:

```
place_id, place (PlaceExtraction), confidence, requires_confirmation, source_url
```

New pipeline returns `list[ExtractionResult] | ProvisionalResponse` — different shape. The product repo (NestJS) depends on the current contract.

**Missing:**
- `PlaceExtraction` schema (LLM output shape with `place_name`, `address`, `cuisine`, `price_range`)
- `requires_confirmation` flow (the 0.30–0.70 band)
- `place_id` (UUID of saved record)
- Multi-place support needs a new response schema — probably `list[ExtractPlaceResponse]`

---

## 3. No database persistence

Current service handles steps 6–9 after confidence scoring:

- **Dedup** by `(external_provider, external_id)` via `PlaceRepository`
- **Write Place** to PostgreSQL
- **Dispatch PlaceSaved** event (taste model update)
- **Generate + save embedding** via `VoyageEmbedder` + `EmbeddingRepository`

The cascade stops at validation. None of this exists in the new design. Either `ExtractionPipeline` owns persistence or a separate orchestrator wraps the pipeline and handles DB writes.

---

## 4. PlaceExtraction schema drift

Current `PlaceExtraction`:

```
place_name, address, cuisine, price_range
```

New `ExtractionResult`:

```
place_name, address, city, cuisine, confidence, resolved_by, corroborated, external_provider, external_id
```

- `city` is new — `Place` DB model has no `city` column (needs Alembic migration)
- `price_range` is gone — still needed for taste model signals
- `address` is nullable in the new design but required in the current schema
- Extraction output and validation output are mixed in one type. Currently these are separate: `PlaceExtraction` (LLM output) vs `PlacesMatchResult` (Google validation)

---

## 5. Missing plain text path

Current system handles two input types: TikTok URLs and plain text ("that ramen place on 5th street"). The new cascade is entirely URL/video-focused. `PlainTextExtractor` has no equivalent enricher.

**Where it fits:** A `PlainTextEnricher` that runs when `context.url is None` and populates candidates directly from `supplementary_text` via LLM NER. Or `LLMNEREnricher` handles this — but only if its caption-to-supplementary_text fallback is reliable for pure text inputs.

---

## 6. Provider abstraction violations (ADR-038)

Several enrichers hardcode external dependencies:

- `TikTokOEmbedEnricher` — httpx call inline, should use injected client
- `LLMNEREnricher` — comment says "Send text to GPT-4o-mini" — must use `InstructorClient` via config role, never hardcode model names
- `WhisperAudioEnricher` — references Groq directly, needs a protocol
- `VisionFramesEnricher` — references GPT-4o-mini vision, needs config role
- `SubtitleCheckEnricher` — references yt-dlp, needs abstraction if swappable

**Fix:** Enrichers receive dependencies via constructor injection. Factory in `deps.py` wires them.

---

## 7. Dependency injection missing

`ExtractionPipeline.__init__` constructs all enrichers internally:

```python
oembed = CircuitBreakerEnricher(enricher=TikTokOEmbedEnricher(), ...)
```

This violates the project's DI pattern (`Depends()` only, no construction inside functions — ADR-019). Enrichers should be injected, not self-constructed.

---

## 8. Config integration incomplete

`ExtractionConfig` and `ConfidenceConfig` are standalone dataclasses. The existing system loads everything from `config/app.yaml` through `AppConfig`. The new config needs to live under `AppConfig.extraction` as Pydantic models that `app.yaml` can populate.

**Also missing from config:**
- `tiktok_oembed` timeout/URL (currently in `ExternalServicesConfig`)
- yt-dlp settings
- Whisper/Groq settings
- Vision model settings
- Background dispatch timeouts (8s whisper, 10s vision)

---

## 9. Confidence formula changed

Current: `base + places_modifier` (additive, capped at 0.95)

New: `base × match_modifier + bonus` (multiplicative)

This changes every confidence score in the system. The `match_modifier` concept replaces `PlacesMatchQuality` enum modifiers. This needs an ADR since it changes scoring behavior.

---

## 10. No Langfuse tracing (ADR-025)

Every LLM call must be traced via Langfuse. None of the enrichers attach Langfuse callbacks. `LLMNEREnricher`, `SubtitleCheckEnricher` (LLM post-processing), `VisionFramesEnricher`, and `WhisperAudioEnricher` all make LLM/model calls without tracing.

---

## 11. ExtractionPending needs a handler

`ExtractionPending` event is dispatched but no handler is registered. The current `EventDispatcher` in `deps.py` registers handlers by event type string.

**Needed:**
- A handler that receives `ExtractionPending`, runs background enrichers, dedup, validation, and persists results
- Registration in `deps.py`
- A way to notify the client when background processing completes (webhook? polling endpoint?)

---

## 12. Missing error handling

Current service raises typed errors mapped to HTTP status codes:

- `ValueError` → 400
- `UnsupportedInputError` → 422
- `ExtractionFailedNoMatchError` → 422

The new pipeline returns `ProvisionalResponse` instead of raising (which is fine), but still needs error cases for:

- Empty input
- All enrichers fail (no candidates AND no background levels available)
- Google Places API hard failure during validation
