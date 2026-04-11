# Research: Taste Model

**Branch**: `008-taste-model` | **Date**: 2026-03-31

---

## 1. EMA Update Algorithm

**Decision**: Gain-weighted EMA with separate positive/negative formulas, dimension-specific α values.

**Rationale**: Spotify's ablation studies (RecSys 2025) confirm different taste dimensions evolve at different speeds. A single α collapses this signal. Gain-weighted α means a strong signal (accepted recommendation, gain 2.0) moves the vector further than a weak one (save, gain 1.0). The research doc specifies two formulas:

- Positive: `v_new = α × |gain| × v_observation + (1 − α × |gain|) × v_current`
- Negative: `v_new = v_current − α × |gain| × (v_observation − v_prior)`

**Alternatives considered**:
- Fixed α for all dimensions: rejected — collapses timescale differences between stable prefs (price_comfort) and situational ones (distance_tolerance)
- Matrix factorization (ALS): deferred — appropriate at scale with many users, overkill for current user count
- Online training (TikTok Monolith): deferred — no infrastructure for streaming parameter updates

---

## 2. Interaction Log as Source of Truth

**Decision**: Interaction log is canonical and append-only. TasteModel table is a derived cache. gain is stored at write time.

**Rationale**: Netflix three-tier architecture pattern. The cache is reconstructable from the log. Storing gain at write time means changing gain configuration never requires rewriting historical data — a critical operational property. If gain values need retroactive adjustment for A/B testing, replay the log with new values.

**Alternatives considered**:
- Update taste_model table directly (no log): rejected — loses audit trail, prevents replay, makes A/B testing of gain values impossible
- Event sourcing with full replay on every consult: rejected — too slow for query-time use; the cache exists precisely to avoid per-query replay

---

## 3. Personalization Routing (interaction_count thresholds)

**Decision**: Three paths driven by interaction_count column read at query time.
- 0 interactions: all-0.5 defaults (stub; full location/time-weighted priors deferred)
- 1–9: 40% stored vector blended with 60% all-0.5 defaults
- ≥10: stored vector returned directly

**Rationale**: Yelp's hybrid model shows content-based features (defaults) dominate for tail users while collaborative signals dominate for head users. The confidence formula `1 − e^(−n/10)` reaches 0.63 at n=10, providing a natural switchover. K-means cluster bootstrapping for zero-interaction users (seeding from nearest centroid) is a meaningful improvement but deferred — 0.5 defaults are a valid cold-start stub.

**Alternatives considered**:
- Confidence as continuous blend weight (instead of three discrete paths): architecturally cleaner, but requires more complex ranking integration; deferred
- K-means seeding at 0 interactions: research doc specifies this, but no user base exists yet to cluster; deferred until interaction_count ≥ 10 exists for a meaningful user pool

---

## 4. EventDispatcher Pattern

**Decision**: Services dispatch named Pydantic domain events. An EventDispatcher, injected per-request via FastAPI Depends(), holds a registry mapping event type → handler callable. Handlers are registered in `deps.py` (API wiring layer) per ADR-043. Background execution via FastAPI BackgroundTasks.

**Rationale**: Directly specified in ADR-043 (2026-03-28). Design session on 2026-03-31 validated the full call chain. `deps.py` owns the registry because it already owns all service construction; the registry must be per-request because it captures a per-request db_session.

**Alternatives considered**:
- Redis pub/sub for async event delivery: architecturally sound but adds a broker dependency and out-of-process complexity for what is currently a single-process background task
- Python `asyncio` queues: process-scoped, not request-scoped; loses per-request session management
- Direct service import: explicitly forbidden by ADR-043 and ADR-036

---

## 5. Embedding Failure Handling (BackgroundTasks interaction)

**Decision**: Option A — embedding failure is non-fatal. Catch the exception, log it, continue to dispatch PlaceSaved, return HTTP 200. Add a TODO marking the need for a backfill job.

**Rationale**: FastAPI only runs BackgroundTasks after a successful (2xx) response. The dispatch sits before the embedding block. If embedding raises and returns 500, the background queue is abandoned — the taste model silently diverges from the places table. Option A ensures the taste signal is always captured when a place is saved. A missing embedding is a known, queryable state (places LEFT JOIN embeddings WHERE vector IS NULL) that a future backfill job can resolve. The user's save is confirmed regardless.

**Alternatives considered**:
- Option B (dispatch after embedding): cleaner invariant — only places with embeddings get taste signals. Rejected because it makes the taste signal contingent on NestJS retrying after a 500, which is not guaranteed.

---

## 6. New Endpoint: POST /v1/feedback

**Decision**: A new `POST /v1/feedback` endpoint receives recommendation acceptance/rejection signals from NestJS. The route handler dispatches `RecommendationAccepted` or `RecommendationRejected` events through the EventDispatcher.

**Rationale**: RecommendationAccepted and RecommendationRejected are in ADR-043's current scope. NestJS currently writes accepted/rejected state to its own recommendations table (ADR-033), but there is no path for this repo to receive those signals. A new endpoint is required. It follows ADR-018 (separate router module), ADR-034 (facade pattern — one service call), ADR-017 (Pydantic request/response).

**Constitution note**: Constitution VIII states "Two endpoints only." This is stale — `POST /v1/recall` was added after the constitution was written and is live. ADR-043 explicitly mandates wiring for accepted/rejected, which requires a feedback endpoint. The feedback endpoint is in scope under ADR-043 authority.

---

## 7. Config Structure for Taste Model

**Decision**: Add `taste_model:` and `ranking:` sections to `config/app.yaml`. Expose via new Pydantic classes `TasteModelConfig` and `RankingConfig` added to `AppConfig`.

**Rationale**: ADR-029 mandates all non-secret config in `app.yaml`. No floats hardcoded in code. Pattern matches existing `extraction:`, `recall:`, `embeddings:` sections. Config is injectable via `Depends(get_config)` for testing overrides.

---

## 8. Constitution Staleness Flags

Two items in `.specify/memory/constitution.md` are stale and should be updated separately (not blocking this feature):

1. **Constitution VIII — "Two endpoints only"**: Should reflect three current endpoints plus the new feedback endpoint.
2. **Constitution VI — migration ownership**: ADR-030 is the binding decision — Alembic owns AI tables in this repo; TypeORM in the product repo manages users and user_settings.
