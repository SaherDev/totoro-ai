# Research: Place Extraction Endpoint (Phase 2)

**Branch**: `002-extract-place` | **Date**: 2026-03-24

No NEEDS CLARIFICATION items were found — the stack is fully defined by existing ADRs and the current codebase. This file documents the key design decisions reached through reading the codebase and reference materials.

---

## 1. Instructor integration with existing LLM provider abstraction

**Decision**: Add `get_instructor_client(role: str) -> InstructorClient` to `src/totoro_ai/providers/llm.py`. `InstructorClient` is a thin wrapper that holds an instructor-patched async OpenAI client and the config-resolved model name. The wrapper exposes a single typed `extract()` method that callers use instead of calling Instructor directly. This keeps the config-driven model selection (ADR-020) intact — no model name is hardcoded in extractor classes.

**Rationale**: Instructor's `from_openai()` wraps an `AsyncOpenAI` client. The model name must be passed at call time, not at client construction. A wrapper class bundles both so extractor classes receive a single injectable dependency and never touch config directly.

**Alternatives considered**:
- `instructor.from_provider("openai/gpt-4o-mini")` inline in extractors — rejected, hardcodes model name, violates ADR-020.
- Separate `providers/instructor.py` file — rejected, unnecessary split when `llm.py` already owns provider concerns.

---

## 2. TikTok oEmbed HTTP call

**Decision**: Use `httpx.AsyncClient` with a 3-second timeout for the oEmbed call (`GET https://www.tiktok.com/oembed?url={url}`). The `TikTokExtractor` creates the client at extract time (not at construction) to keep the class stateless. On timeout or non-200 response, the extractor raises a domain exception that the service maps to a 500 error.

**Rationale**: `httpx` is already in the project (dev deps) and is the idiomatic async HTTP client for FastAPI. Moving it to production deps is the only change required. The 3-second timeout was set in the clarification session to fit within the 10-second total response budget.

**Alternatives considered**:
- `aiohttp` — already have httpx, no reason to add another HTTP client.
- `requests` (sync) — incompatible with async FastAPI handlers.

**New production dependency**: `httpx = "^0.28"` (promote from dev group to main).

---

## 3. Instructor exception handling

**Decision**: Handle all three Instructor exception types in each extractor's `extract()` method:
- `IncompleteOutputException` → log warning, return `None` (caller treats as extraction failure)
- `InstructorRetryException` → log error with attempt count, return `None`
- `ValidationError` (pydantic) → log error, re-raise (hard schema violation, not retryable)

The service layer catches `None` from `extract()` and raises `ExtractionFailedNoMatchError`.

**Rationale**: These three types cover all Instructor failure modes documented in the Phase 2 learning material. Returning `None` on soft failures lets the service decide the response strategy without the extractor knowing about HTTP error codes.

---

## 4. Google Places Text Search API

**Decision**: `GooglePlacesClient.validate_place()` calls the Places API `findplacefromtext` endpoint with `inputtype=textquery` and `fields=name,formatted_address,place_id`. Match quality is computed by comparing the extracted name to the returned name using `difflib.SequenceMatcher`:
- Ratio ≥ 0.95 → `EXACT`
- Ratio ≥ 0.80 → `FUZZY`
- Place found but name ratio < 0.80 → `CATEGORY_ONLY`
- No result → `NONE`

API key is read from `os.environ["GOOGLE_PLACES_API_KEY"]` — never from config files (FR-014).

**Rationale**: Text Search is the correct endpoint for name-based lookup. The `findplacefromtext` endpoint accepts a free-text query and returns the best match. String similarity provides a deterministic match quality without requiring an additional LLM call.

**Alternatives considered**:
- Nearby Search — requires coordinates; not always available from caption text.
- Place ID lookup — requires a known place ID, not applicable at extraction time.

---

## 5. DB model additions (Alembic migration required)

**Decision**: Add three nullable columns to the `places` table:

| Column | Type | Notes |
|--------|------|-------|
| `google_place_id` | `VARCHAR, nullable` | External ID from Google Places — never PK (clarification Q2) |
| `confidence` | `FLOAT, nullable` | Score at time of save (only populated for saved records, ≥ 0.70) |
| `source` | `VARCHAR, nullable` | Extraction source: `CAPTION`, `PLAIN_TEXT`, `SPEECH` (Phase 3), `OCR` (Phase 3) |

One new Alembic migration: `add_extraction_metadata_to_places`.

**Rationale**: UUID `id` is already the PK. `google_place_id` is stored as a lookup aid and future deduplication key — not a PK — so swapping Google Places for another provider (e.g. Foursquare) only requires adding a `foursquare_place_id` column, not a PK migration.

---

## 6. Confidence weights in config

**Decision**: All weights live in `config/.local.yaml` under `extraction.confidence_weights`:

```yaml
extraction:
  confidence_weights:
    base_scores:
      CAPTION: 0.70
      PLAIN_TEXT: 0.70
      SPEECH: 0.60      # Phase 3 — defined now, no implementation yet
      OCR: 0.55         # Phase 3 — defined now, no implementation yet
    places_modifiers:
      EXACT: 0.20
      FUZZY: 0.15
      CATEGORY_ONLY: 0.10
      NONE_CAP: 0.30    # max score when no Places match
    multi_source_bonus: 0.10
    max_score: 0.95
  thresholds:
    store_silently: 0.70
    require_confirmation: 0.30
```

`compute_confidence()` reads these at call time via `load_yaml_config(".local.yaml")`.

---

## 7. New production dependency

**Decision**: Add `instructor` to pyproject.toml main dependencies.

```toml
instructor = "^1.0"
```

Also promote `httpx` from dev to main:
```toml
httpx = "^0.28"
```

---

## 8. Constitution inconsistency (non-blocking)

The constitution (Section VI) states "Prisma in totoro owns all migrations." This contradicts ADR-030, CLAUDE.md, and the existing Alembic migration files already in the repo. The existing setup (Alembic for AI tables) is correct. The constitution text is stale on this point. No blocking action — proceed per ADR-030.
