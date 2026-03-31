# Implementation Plan: Taste Model

**Branch**: `008-taste-model` | **Date**: 2026-03-31 | **Spec**: [spec.md](spec.md)

## Summary

Build a deterministic behavioral taste model that learns user preferences from saves, recommendation feedback, and onboarding signals. Updates run as FastAPI background tasks via a domain event dispatcher, decoupled from ExtractionService. The taste vector drives personalization in the consult ranking step. No LLM calls in the update path.

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**: FastAPI 0.115, SQLAlchemy 2.0 async, Pydantic 2.10, asyncpg, Alembic
**Storage**: PostgreSQL — modifying `taste_model` table, creating `interaction_log` table
**Testing**: pytest (`asyncio_mode = "auto"`, no `@pytest.mark.asyncio` needed)
**Target Platform**: Linux server (Railway)
**Project Type**: Web service (FastAPI)
**Performance Goals**: Taste model update must not add latency to HTTP response (runs post-response via BackgroundTasks)
**Constraints**: No LLM calls in this feature. All floats from config. mypy --strict must pass. ruff check must pass.
**Scale/Scope**: Single-user taste vector updates. No batch processing in scope.

## Constitution Check

| Gate | Status | Notes |
|------|--------|-------|
| ADR-001: src layout | PASS | All new code in `src/totoro_ai/` |
| ADR-002: Hybrid directory | PASS | Events/taste in `core/`, repository in `db/repositories/` |
| ADR-003: ruff + mypy strict | PASS | Enforced in Done When criteria |
| ADR-004: tests mirror src | PASS | Test files planned for each new module |
| ADR-008: extract-place not LangGraph | PASS | EventDispatcher is not LangGraph |
| ADR-014: /v1 prefix | PASS | New feedback route uses /v1 prefix from APIRouter |
| ADR-017: Pydantic everywhere | PASS | FeedbackRequest/Response Pydantic models planned |
| ADR-018: Separate router modules | PASS | `routes/feedback.py` planned |
| ADR-019: Depends() for deps | PASS | get_event_dispatcher uses Depends() |
| ADR-025: Langfuse on all traces | PASS | Handlers wrap failures in Langfuse trace |
| ADR-030: Alembic owns taste_model | PASS | Two new Alembic migrations planned |
| ADR-034: Facade on route handlers | PASS | feedback.py dispatches one event, returns |
| ADR-036: Observer via BackgroundTasks | PASS | EventDispatcher + BackgroundTasks pattern |
| ADR-038: Protocol for all swappable deps | PASS | TasteModelRepository behind Protocol |
| ADR-043: EventDispatcher pattern | PASS | Central constraint — entire design follows it |
| Constitution VI: write ownership | PASS | taste_model write owned by this repo |
| Constitution VIII: "Two endpoints" | FLAG (stale) | recall already added; feedback endpoint follows same pattern. Not blocking — ADR-043 mandates it. Constitution should be updated separately. |

**Constitution verdict**: PASS. One stale clause noted (VIII), not blocking.

## Project Structure

### Documentation (this feature)

```text
specs/008-taste-model/
├── plan.md                       # This file
├── research.md                   # Phase 0 — decisions and rationale
├── data-model.md                 # Phase 1 — entities, columns, config, routing logic
├── contracts/
│   └── feedback-endpoint.md     # Phase 1 — POST /v1/feedback contract
└── tasks.md                     # Phase 2 output (/speckit.tasks — not yet created)
```

### Source Code

```text
src/totoro_ai/
├── api/
│   ├── routes/
│   │   └── feedback.py          # NEW — POST /v1/feedback facade
│   ├── schemas/
│   │   └── feedback.py          # NEW — FeedbackRequest, FeedbackResponse
│   └── main.py                  # MODIFY — include feedback_router
├── core/
│   ├── events/                  # NEW package
│   │   ├── __init__.py
│   │   ├── events.py            # DomainEvent, PlaceSaved, RecommendationAccepted,
│   │   │                        #   RecommendationRejected, OnboardingSignal
│   │   ├── dispatcher.py        # EventDispatcherProtocol, EventDispatcher
│   │   └── handlers.py          # on_place_saved, on_recommendation_accepted,
│   │                            #   on_recommendation_rejected, on_onboarding_signal
│   ├── taste/                   # NEW package
│   │   ├── __init__.py
│   │   └── service.py           # TasteModelService
│   ├── ranking/                 # NEW package
│   │   ├── __init__.py
│   │   └── service.py           # RankingService stub
│   └── extraction/
│       └── service.py           # MODIFY — add event_dispatcher param, dispatch PlaceSaved
├── db/
│   ├── models.py                # MODIFY — TasteModel new columns, InteractionLog model
│   └── repositories/
│       ├── __init__.py          # MODIFY — export new repository
│       └── taste_model_repository.py  # NEW — Protocol + SQLAlchemy impl
└── core/
    └── config.py                # MODIFY — TasteModelConfig, RankingConfig, AppConfig

alembic/versions/
├── XXXX_update_taste_model_table.py       # NEW — migration 1
└── XXXX_create_interaction_log_table.py   # NEW — migration 2

config/
└── app.yaml                     # MODIFY — add taste_model:, ranking: sections

tests/
├── core/
│   ├── events/
│   │   └── test_dispatcher.py   # NEW
│   ├── taste/
│   │   └── test_service.py      # NEW
│   └── ranking/
│       └── test_service.py      # NEW
└── db/
    └── repositories/
        └── test_taste_model_repository.py  # NEW
```

## Implementation Tasks

Tasks are ordered by dependency. Each task is independently completable and testable.

---

### Task 1 — Config: add taste_model and ranking sections

**Files**: `config/app.yaml`, `src/totoro_ai/core/config.py`

Add `taste_model:` (with `ema:` and `signals:` subsections) and `ranking:` (with `weights:` subsection) to `app.yaml`. Add corresponding Pydantic classes to `config.py` and extend `AppConfig`.

New Pydantic classes needed:
- `TasteModelEmaConfig` — 8 dimension α values
- `TasteModelSignalsConfig` — 8 signal gain values
- `TasteModelConfig` — composes ema + signals
- `RankingWeightsConfig` — 4 ranking weights
- `RankingConfig` — composes weights

**Verify**: `get_config().taste_model.ema.price_comfort == 0.03`, `get_config().ranking.weights.taste_similarity == 0.40`. mypy passes.

---

### Task 2 — Migration 1: update taste_model table

**Files**: `alembic/versions/XXXX_update_taste_model_table.py`

- Rename column `performance_score` → `eval_score` (nullable Float)
- Add column `confidence` (Float, server_default='0.0', nullable=False)
- Add column `interaction_count` (Integer, server_default='0', nullable=False)

Run with `poetry run alembic upgrade head`. Verify no errors on a clean DB and on a DB with existing taste_model rows.

**Verify**: `alembic upgrade head` runs clean. `alembic downgrade -1` reverses cleanly.

---

### Task 3 — Migration 2: create interaction_log table

**Files**: `alembic/versions/XXXX_create_interaction_log_table.py`

Create `interaction_log` table. Create `signaltype` PostgreSQL enum with values: `save, accepted, rejected, ignored, repeat_visit, search_accepted, onboarding_explicit`. FK from `place_id` to `places.id` with `ON DELETE SET NULL`. Index on `user_id`.

**Verify**: `alembic upgrade head` runs clean. `alembic downgrade -1` drops table and enum cleanly.

---

### Task 4 — ORM: update TasteModel model, add InteractionLog model

**Files**: `src/totoro_ai/db/models.py`

Update `TasteModel`:
- Remove `performance_score` mapped_column
- Add `eval_score: Mapped[float | None]`
- Add `confidence: Mapped[float]` (default 0.0, not null)
- Add `interaction_count: Mapped[int]` (default 0, not null)

Add `InteractionLog(Base)`:
- `id`, `user_id` (indexed), `signal_type` (Mapped[str]), `place_id` (nullable FK → places.id), `gain`, `context` (JSONB), `created_at`

Add `SignalType` Python Enum in `models.py` with all 7 values.

**Verify**: mypy passes. Existing tests still pass.

---

### Task 5 — Repository: TasteModelRepository

**Files**: `src/totoro_ai/db/repositories/taste_model_repository.py`, `src/totoro_ai/db/repositories/__init__.py`

Define `TasteModelRepository` Protocol with three methods:
- `get_by_user_id(user_id: str) -> TasteModel | None`
- `upsert(user_id, parameters, confidence, interaction_count) -> TasteModel`
- `log_interaction(user_id, signal_type, place_id, gain, context) -> None`

Implement `SQLAlchemyTasteModelRepository`. Export both from `__init__.py`. All DB writes wrapped in try/except/rollback.

**Verify**: Unit tests with mock session. mypy passes.

---

### Task 6 — Events: domain event models

**Files**: `src/totoro_ai/core/events/__init__.py`, `src/totoro_ai/core/events/events.py`

Define:
- `DomainEvent(BaseModel)` — base
- `PlaceSaved(DomainEvent)` — `user_id: str`, `place_id: str`
- `RecommendationAccepted(DomainEvent)` — `user_id: str`, `recommendation_id: str`, `place_id: str`
- `RecommendationRejected(DomainEvent)` — `user_id: str`, `recommendation_id: str`, `place_id: str`
- `OnboardingSignal(DomainEvent)` — `user_id: str`, `place_id: str`, `confirmed: bool`

**Verify**: All models instantiate correctly. mypy passes.

---

### Task 7 — Events: EventDispatcher

**Files**: `src/totoro_ai/core/events/dispatcher.py`

Define:
- `EventHandler = Callable[[DomainEvent], Coroutine[Any, Any, None]]`
- `EventDispatcherProtocol(Protocol)` — `dispatch(event: DomainEvent) -> None`
- `EventDispatcher` — concrete; holds `BackgroundTasks` + `registry: dict[type[DomainEvent], EventHandler]`; `dispatch()` looks up `type(event)` in registry, calls `background_tasks.add_task(handler, event)`

**Verify**: Unit test confirms `background_tasks.add_task` is called with correct handler. Unknown event type is ignored (no KeyError). mypy passes.

---

### Task 8 — Taste: TasteModelService

**Files**: `src/totoro_ai/core/taste/__init__.py`, `src/totoro_ai/core/taste/service.py`

`TasteModelService(taste_repo: TasteModelRepository, config: TasteModelConfig)`:

- `handle_place_saved(user_id, place_id, place_metadata)` — gain 1.0
- `handle_recommendation_accepted(user_id, place_id)` — gain 2.0
- `handle_recommendation_rejected(user_id, place_id)` — gain −1.5
- `handle_onboarding_signal(user_id, place_id, confirmed)` — gain 1.2 / −0.8
- `get_taste_vector(user_id) -> dict[str, float]` — returns routed vector

EMA update logic (positive and negative formulas). Confidence recomputation after each update. Always log_interaction first, then upsert.

**DEFAULT_VECTOR** = `{dim: 0.5 for dim in 8 dimensions}` — module-level constant.

Personalization routing thresholds: 0 → default, 1–9 → 40/60 blend, ≥10 → stored vector.

**Verify**: Unit tests cover all four handlers, get_taste_vector at all three routing paths, confidence curve at counts 0/5/10/20, negative EMA direction, gain values from config (not hardcoded). mypy passes.

---

### Task 9 — Events: handlers

**Files**: `src/totoro_ai/core/events/handlers.py`

Four async handler functions:
- `on_place_saved(event: PlaceSaved, taste_service: TasteModelService) -> None`
- `on_recommendation_accepted(event: RecommendationAccepted, taste_service: TasteModelService) -> None`
- `on_recommendation_rejected(event: RecommendationRejected, taste_service: TasteModelService) -> None`
- `on_onboarding_signal(event: OnboardingSignal, taste_service: TasteModelService) -> None`

Each wraps the taste_service call in try/except. On failure: `logger.error(...)` + Langfuse span with error property set. No re-raise — background task failures must not propagate.

**Verify**: Handler failure logs error without raising. Langfuse trace created on failure. mypy passes.

---

### Task 10 — ExtractionService: add EventDispatcher, dispatch PlaceSaved

**Files**: `src/totoro_ai/core/extraction/service.py`

Add `event_dispatcher: EventDispatcherProtocol` to `__init__`.

In `run()`: after successful `_place_repo.save(place)`, dispatch `PlaceSaved(user_id=user_id, place_id=place_id)`. Then wrap embedding in try/except — catch, log, add TODO for backfill job, continue (Option A: non-fatal). Remove existing `raise` from embedding exception handler.

```python
# TODO: backfill job needed — places without embeddings won't appear in vector recall
# until re-embedded. Track via: SELECT id FROM places LEFT JOIN embeddings
# ON places.id = embeddings.place_id WHERE embeddings.place_id IS NULL
```

**Verify**: Existing extraction tests still pass. New test: embedding failure returns 200 with valid place_id. Dispatch is called after save, before embedding. mypy passes.

---

### Task 11 — deps.py: get_event_dispatcher, update get_extraction_service

**Files**: `src/totoro_ai/api/deps.py`

Add:
- `build_taste_service(db_session) -> TasteModelService` — builds taste service
- `build_handler_registry(taste_service) -> dict[type[DomainEvent], EventHandler]` — binds taste service to handlers via `functools.partial`
- `async get_event_dispatcher(background_tasks: BackgroundTasks, db_session: Depends(get_session)) -> EventDispatcher`
- Update `get_extraction_service` to accept `event_dispatcher: EventDispatcher = Depends(get_event_dispatcher)`

**Verify**: ExtractionService constructed with event_dispatcher. BackgroundTasks flows through correctly. mypy passes.

---

### Task 12 — Feedback route and schema

**Files**: `src/totoro_ai/api/schemas/feedback.py`, `src/totoro_ai/api/routes/feedback.py`

`FeedbackRequest(BaseModel)`: `user_id: str`, `recommendation_id: str`, `place_id: str`, `signal: Literal["accepted", "rejected"]`

`FeedbackResponse(BaseModel)`: `status: Literal["received"]`

Route `POST /feedback`: receives `FeedbackRequest`, maps `signal` to `RecommendationAccepted` or `RecommendationRejected`, calls `event_dispatcher.dispatch(event)`, returns `FeedbackResponse(status="received")`.

Route handler has one additional dependency: `event_dispatcher: EventDispatcher = Depends(get_feedback_event_dispatcher)`. Add `get_feedback_event_dispatcher` to `deps.py` — same construction as `get_event_dispatcher`.

**Verify**: POST /v1/feedback with `signal="accepted"` dispatches `RecommendationAccepted`. Unknown signal returns 422. mypy passes.

---

### Task 13 — main.py: include feedback router

**Files**: `src/totoro_ai/api/main.py`

Import `feedback_router` from `routes/feedback.py`. Include in `router.include_router(feedback_router, prefix="")`.

**Verify**: `GET /v1/health` still returns 200. `POST /v1/feedback` appears in OpenAPI schema.

---

### Task 14 — Ranking stub

**Files**: `src/totoro_ai/core/ranking/__init__.py`, `src/totoro_ai/core/ranking/service.py`

`RankingService(config: RankingConfig)`:
- `rank(candidates: list[dict], taste_vector: dict[str, float]) -> list[dict]` — computes weighted score per candidate, returns sorted list. All weights from `config.weights`. No hardcoded floats.

Scoring formula stub:
```
score = (taste_similarity * weights.taste_similarity
       + distance_score * weights.distance
       + price_fit * weights.price_fit
       + popularity * weights.popularity)
```

Where input fields are provided in the candidate dict. Missing fields default to 0.5.

**Verify**: Returns candidates sorted by descending score. Weights sum to 1.0. mypy passes.

---

### Task 15 — ConsultService: integrate taste vector

**Files**: `src/totoro_ai/core/consult/service.py`, `src/totoro_ai/api/deps.py`

Add `taste_service: TasteModelService` and `ranking_service: RankingService` to `ConsultService.__init__`.

In `consult()`: call `taste_vector = await taste_service.get_taste_vector(user_id)` before ranking step. Pass `taste_vector` to `ranking_service.rank(candidates, taste_vector)`.

Add `get_consult_service` dependency to `deps.py` that injects both services.

**Verify**: ConsultService calls get_taste_vector. Zero-interaction users still receive a response (all-0.5 defaults). mypy passes.

---

## Done When

- [ ] `poetry run alembic upgrade head` runs clean with no errors
- [ ] A saved place triggers an `interaction_log` entry with `signal_type=save` and `gain=1.0`
- [ ] An onboarding confirmation triggers an `interaction_log` entry with `signal_type=onboarding_explicit` and `gain=1.2`
- [ ] `taste_model.confidence` updates correctly after each interaction (verified against formula)
- [ ] `get_taste_vector` returns all-0.5 defaults for a user with zero interactions
- [ ] `get_taste_vector` returns stored vector for a user with 10+ interactions
- [ ] Embedding failure in extract-place returns HTTP 200 with valid place_id; taste model still updates
- [ ] `POST /v1/feedback` with `signal=accepted` dispatches `RecommendationAccepted` event
- [ ] Consult ranking calls `get_taste_vector` and uses the result in scoring
- [ ] `poetry run pytest` passes
- [ ] `poetry run ruff check src/` passes
- [ ] `poetry run mypy src/` passes
