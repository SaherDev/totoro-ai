# Taste Model Architecture

The taste model builds a per-user preference vector from behavioral signals. Each interaction (save, accept, reject, onboarding) updates an 8-dimensional vector via Exponential Moving Average (EMA). The vector feeds into the ranking service to personalize recommendations.

## Data Flow

```
User Action (save place / accept rec / reject rec / onboarding)
    │
    ▼
Endpoint (POST /v1/extract-place or POST /v1/feedback)
    │
    ▼
Create DomainEvent (PlaceSaved, RecommendationAccepted, etc.)
    │
    ▼
EventDispatcher.dispatch(event) → queued as BackgroundTask
    │
    ▼
HTTP 200 returned to caller
    │
    ▼
Background Task Runs
    ├── EventHandlers.on_X(event)
    │   └── TasteModelService.handle_X(...)
    │       ├── log_interaction() → append-only audit log
    │       └── _apply_taste_update()
    │           ├── _place_to_metadata(place) → extract signal fields
    │           ├── _get_observation_value() per dimension → config lookup
    │           ├── EMA: v_new = α·|g|·v_obs + (1 - α·|g|)·v_current
    │           └── repository.upsert() → atomic SQL increment
    └── Langfuse trace (if enabled)
```

## Taste Dimensions

8 independent preference axes, each a float in [0.0, 1.0], initialized to 0.5 (neutral):

| Dimension | What it captures | EMA (α) | Learning speed |
|-----------|-----------------|---------|----------------|
| price_comfort | Price range preference | 0.03 | Slow (stable) |
| dietary_alignment | Dietary restrictions | 0.03 | Slow (stable) |
| cuisine_frequency | Cuisine engagement frequency | 0.07 | Moderate |
| ambiance_preference | Venue atmosphere | 0.07 | Moderate |
| crowd_tolerance | Crowding preference | 0.10 | Faster |
| cuisine_adventurousness | Willingness to try new cuisines | 0.10 | Faster |
| time_of_day_preference | Preferred meal time | 0.15 | Fastest |
| distance_tolerance | Travel distance willingness | 0.15 | Fastest |

Lower α = more conservative, weights history heavily. Higher α = more responsive to recent signals.

## Signal Types and Gains

| Signal | Gain | Direction | Trigger |
|--------|------|-----------|---------|
| save | 1.0 | positive | User saves a place via extract-place |
| accepted | 2.0 | positive | User accepts a recommendation |
| rejected | -1.5 | negative | User rejects a recommendation |
| onboarding_explicit (confirmed) | 1.2 | positive | User confirms onboarding preference |
| onboarding_explicit (dismissed) | -0.8 | negative | User dismisses onboarding preference |
| ignored | -0.5 | negative | Place shown but not engaged |
| repeat_visit | 3.0 | positive | User visits a place again |
| search_accepted | 1.5 | positive | User accepts a place from search |

Gain magnitude modulates the learning rate: `alpha_gain = alpha * abs(gain)`.

## EMA Update Formula

For each dimension on every signal:

**Positive signals** (save, accepted, onboarding confirmed):
```
v_new = alpha_gain * v_observation + (1 - alpha_gain) * v_current
```
Moves the vector toward the observed value.

**Negative signals** (rejected, onboarding dismissed):
```
v_new = v_current - alpha_gain * (v_observation - v_current)
```
Moves the vector away from the observed value.

Where:
- `alpha_gain = ema[dimension] * abs(gain)` — signal-modulated learning rate
- `v_observation` — looked up from config observation mappings (0.0–1.0)
- `v_current` — current dimension value from taste_model (or 0.5 for new users)
- Result clamped to [0.0, 1.0]

## Confidence Formula

Computed atomically in SQL on every interaction:

```
confidence = 1 - exp(-interaction_count / 10.0)
```

| Interactions | Confidence |
|-------------|-----------|
| 1 | 0.095 |
| 2 | 0.181 |
| 3 | 0.259 |
| 5 | 0.393 |
| 10 | 0.632 |
| 20 | 0.865 |
| 50 | 0.993 |

Asymptotically approaches 1.0. Early signals are weighted lower confidence.

## Cold Start Blending

When `interaction_count < 10`, `get_taste_vector()` blends personal preferences with defaults:

```
blended[dim] = personal[dim] * 0.40 + default[dim] * 0.60
```

At 10+ interactions, the full personal vector is returned.

## Observation Mappings

Config-driven lookup tables convert place metadata into observation values per dimension. Located in `config/app.yaml` under `taste_model.observations`.

| Dimension | Metadata field | Example mapping |
|-----------|---------------|----------------|
| price_comfort | price_range | low→1.0, mid→0.5, high→0.0 |
| ambiance_preference | ambiance | casual→0.25, moderate→0.5, upscale→1.0 |
| time_of_day_preference | time_of_day | breakfast→0.0, lunch→0.33, dinner→0.66, late_night→1.0 |
| distance_tolerance | distance | very_close→1.0, nearby→0.66, moderate→0.33, far→0.0 |
| dietary_alignment | dietary | vegan→1.0, vegetarian→0.75, pescatarian→0.5, omnivore→0.25 |
| cuisine_frequency | frequency | rare→0.0, occasional→0.33, frequent→0.66, very_frequent→1.0 |
| cuisine_adventurousness | adventurousness | familiar→0.0, exploration→0.5, experimental→1.0 |
| crowd_tolerance | crowd_level | quiet→0.0, moderate→0.5, busy→1.0 |

Dimensions with no metadata available default to 0.5 (no signal).

Currently populated from place records: `price_range`, `ambiance`, `time_of_day` (derived from `place.created_at`). The remaining 5 dimensions require behavioral history or query-time data and default to 0.5.

## Ranking Integration

`RankingService.rank()` uses the taste vector to score candidates:

```
taste_similarity = 1 / (1 + weighted_euclidean_distance)
```

Where weighted Euclidean distance uses per-dimension EMA rates as weights:

```
distance = sqrt(sum(ema[dim] * (taste[dim] - observation[dim])^2 for dim in dimensions))
```

Final ranking score:

| Factor | Weight |
|--------|--------|
| taste_similarity | 0.40 |
| distance_score | 0.25 |
| price_fit_score | 0.20 |
| popularity_score | 0.15 |

## Database Schema

### taste_model

| Column | Type | Notes |
|--------|------|-------|
| id | VARCHAR | PK |
| user_id | VARCHAR | UNIQUE, indexed |
| model_version | VARCHAR | Currently "1.0" |
| parameters | JSONB | 8-dimension vector `{dim: float}` |
| confidence | FLOAT | `1 - exp(-count/10)` |
| interaction_count | INT | Atomic SQL increment |
| eval_score | FLOAT | Nullable, offline evaluation only |
| created_at | TIMESTAMPTZ | Server default |
| updated_at | TIMESTAMPTZ | Server default, auto-update |

### interaction_log (append-only)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| user_id | VARCHAR | Indexed |
| signal_type | signaltype enum | save, accepted, rejected, etc. |
| place_id | VARCHAR | FK → places.id, ON DELETE SET NULL |
| gain | FLOAT | Positive or negative |
| context | JSON | Location, session, recommendation metadata |
| created_at | TIMESTAMPTZ | Server default |

## Atomic Upsert Pattern

The repository uses a two-step atomic pattern to prevent race conditions:

1. **UPDATE** with `interaction_count = interaction_count + 1` and `confidence = 1 - exp(-(interaction_count + 1) / 10.0)` computed in SQL
2. If 0 rows affected, **INSERT ... ON CONFLICT (user_id) DO UPDATE** with same atomic expressions

The increment and confidence recalculation happen in a single SQL statement — no read-modify-write round trip.

## Event System

| Event | Source | Handler | Service method |
|-------|--------|---------|---------------|
| PlaceSaved | ExtractionService.run() | on_place_saved | handle_place_saved |
| RecommendationAccepted | POST /v1/feedback | on_recommendation_accepted | handle_recommendation_accepted |
| RecommendationRejected | POST /v1/feedback | on_recommendation_rejected | handle_recommendation_rejected |
| OnboardingSignal | (deferred) | on_onboarding_signal | handle_onboarding_signal |

All handlers run as FastAPI `BackgroundTasks` — they execute after HTTP 200 is returned. Handler failures are logged but never propagate to the caller.

## File Map

| Component | Path |
|-----------|------|
| TasteModelService | `src/totoro_ai/core/taste/service.py` |
| TasteModelRepository | `src/totoro_ai/db/repositories/taste_model_repository.py` |
| EventDispatcher | `src/totoro_ai/core/events/dispatcher.py` |
| EventHandlers | `src/totoro_ai/core/events/handlers.py` |
| Domain Events | `src/totoro_ai/core/events/events.py` |
| DB Models | `src/totoro_ai/db/models.py` |
| Config values | `config/app.yaml` (taste_model section) |
| Config classes | `src/totoro_ai/core/config.py` |
| Feedback endpoint | `src/totoro_ai/api/routes/feedback.py` |
| Feedback schemas | `src/totoro_ai/api/schemas/feedback.py` |
| RankingService | `src/totoro_ai/core/ranking/service.py` |
| Dependency injection | `src/totoro_ai/api/deps.py` |
| Tests | `tests/core/taste/test_service_integration.py` |
| Migration (taste_model columns) | `alembic/versions/69cb7399_*.py` |
| Migration (interaction_log) | `alembic/versions/69cb739a_*.py` |
| Migration (ambiance column) | `alembic/versions/94b9f036ae64_*.py` |
