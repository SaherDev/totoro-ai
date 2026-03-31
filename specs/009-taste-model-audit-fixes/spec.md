# Feature Specification: Taste Model Audit Fixes

**Feature Branch**: `009-taste-model-audit-fixes`  
**Created**: 2026-03-31  
**Status**: Draft  

## Clarifications

### Session 2026-03-31

- Q: Should `_increment_and_update_confidence` be deleted or left as dead code after all callers are removed? → A: Delete it entirely (FR-011).
- Q: How should `upsert()` handle concurrent INSERT for a brand-new user where two requests both see rowcount=0? → A: Use `ON CONFLICT (user_id) DO UPDATE SET ...` on the INSERT so it becomes a fully atomic upsert (FR-012).

## User Scenarios & Testing *(mandatory)*

### User Story 1 — EMA Updates Fire for All Signal Types (Priority: P1)

When a user confirms or dismisses a taste chip during onboarding, accepts or rejects a recommendation, or saves a place, the taste model must update all affected dimensions using the EMA formula with the correct gain. Currently onboarding and recommendation signals skip the EMA calculation entirely, meaning the taste vector never moves in response to the strongest behavioral signals.

**Why this priority**: Without EMA updates on onboarding and recommendation signals, the taste model never personalises. A user who confirms 5 taste chips has an identical vector to a user who dismissed all 5. This is the most critical correctness gap in the current implementation.

**Independent Test**: Trigger each signal type in isolation and verify the taste vector changes in the expected direction for the `price_comfort` dimension (the only dimension with a fully populated observation value). Cold-start user starts at 0.5. After a high-price accepted recommendation, `price_comfort` must decrease below 0.5.

**Acceptance Scenarios**:

1. **Given** a user with `price_comfort=0.5`, **When** they save a place with `price_range=high`, **Then** `price_comfort` in `taste_model.parameters` decreases below 0.5.
2. **Given** a user with `price_comfort=0.5`, **When** they accept a recommendation for a `price_range=high` place, **Then** `price_comfort` decreases.
3. **Given** a user with `price_comfort=0.5`, **When** they reject a recommendation for a `price_range=low` place, **Then** `price_comfort` decreases (moving away from 1.0, toward lower values).
4. **Given** a user with `price_comfort=0.5`, **When** an onboarding confirmation fires for a `price_range=low` place (gain +1.2), **Then** `price_comfort` increases toward 1.0.
5. **Given** a user with `price_comfort=0.5`, **When** an onboarding dismissal fires for a `price_range=low` place (gain −0.8), **Then** `price_comfort` decreases (the vector moves away from the observation value).

---

### User Story 2 — Ambiance Dimension Observes Real Place Data (Priority: P2)

The `ambiance_preference` taste dimension currently always receives a neutral observation (0.5) because the Place model stores no ambiance field. Google Places returns atmosphere data that maps to casual/moderate/upscale categories. Adding `ambiance` to places makes `ambiance_preference` a live taste dimension.

**Why this priority**: Ambiance is a primary driver of place choice. Getting real observations for this dimension is the highest-value improvement achievable without behavioral history data, and requires only a migration and a metadata field.

**Independent Test**: Save a place with `ambiance=upscale` and verify `ambiance_preference` moves above its previous value.

**Acceptance Scenarios**:

1. **Given** a place saved with `ambiance=upscale`, **When** the taste update fires, **Then** `ambiance_preference` increases from its prior value.
2. **Given** a place saved with `ambiance=casual`, **When** the taste update fires, **Then** `ambiance_preference` decreases from its prior value.
3. **Given** a place with `ambiance=null`, **When** the taste update fires, **Then** `ambiance_preference` remains unchanged (neutral observation, no movement).
4. **Given** the Alembic migration runs against a database with existing place rows, **Then** all existing rows have `ambiance=null` and no error occurs.

---

### User Story 3 — Time-of-Day Preference Observes Save Time (Priority: P2)

A user who consistently saves places late at night reveals a time-of-day preference. Deriving `time_of_day` from `place.created_at` with four buckets (breakfast/lunch/dinner/late_night) provides a real signal at zero cost — no new data required.

**Why this priority**: Requires no new stored data. `created_at` is already on every place record. Maps directly to an existing config observation table. Low effort, adds a second live taste dimension alongside `price_comfort`.

**Independent Test**: Verify that a place saved at 21:30 (dinner bucket) produces `time_of_day=dinner` in metadata, causing `time_of_day_preference` to move toward 0.66.

**Acceptance Scenarios**:

1. **Given** a place with `created_at` hour 05–10 (UTC), **When** metadata is built, **Then** `time_of_day=breakfast` is included.
2. **Given** a place with `created_at` hour 11–14, **When** metadata is built, **Then** `time_of_day=lunch`.
3. **Given** a place with `created_at` hour 15–20, **When** metadata is built, **Then** `time_of_day=dinner`.
4. **Given** a place with `created_at` hour 21–04, **When** metadata is built, **Then** `time_of_day=late_night`.

---

### User Story 4 — Interaction Count Increments Without Race Condition (Priority: P1)

Two concurrent signals for the same user (e.g., a save and a feedback tap arriving simultaneously) must each increment `interaction_count` independently. The current read-modify-write pattern allows both to read count=5, both to write back 6, silently losing one increment.

**Why this priority**: Silent data loss in `interaction_count` corrupts the `confidence` score and personalization phase routing — a user stays in cold-start phase longer than warranted with no visible error.

**Independent Test**: Inspect the generated SQL — the UPDATE statement must include `interaction_count = interaction_count + 1` with no prior SELECT of the current count value.

**Acceptance Scenarios**:

1. **Given** an existing row with `interaction_count=5`, **When** `upsert()` is called, **Then** the database value becomes 6 via a single SQL UPDATE with no prior SELECT.
2. **Given** a new user (no row exists), **When** `upsert()` is called, **Then** an INSERT is written with `interaction_count=1` and `confidence=1−e^(−0.1)`.
3. **Given** any upsert call, **When** the statement executes, **Then** `confidence` is recomputed as `1 − exp(−(interaction_count + 1) / 10.0)` in the same statement.
4. **Given** two simultaneous signals for a brand-new user, **When** both reach `upsert()` concurrently, **Then** no constraint violation occurs and `interaction_count` reflects both increments.

---

### Edge Cases

- Onboarding or recommendation handler with `place_id` that no longer exists in the database — `_place_to_metadata` returns `{}`, all dimensions default to 0.5, EMA fires with neutral observations (vector moves toward 0.5 rather than skipping entirely).
- Onboarding dismissal (negative gain, gain=−0.8) for a place with `ambiance=null` — only `price_comfort` and `time_of_day_preference` can observe real values; `ambiance_preference` stays unchanged.
- `created_at` is always stored as UTC in the database — time-of-day bucket derivation uses UTC hour, which may not match the user's local time. Acceptable for Phase 3; timezone-aware bucketing is deferred.
- YAML strict parsers may reject `;` as a comment character — must use `#`.
- `_increment_and_update_confidence` becomes unused after all three handlers are migrated to `_apply_taste_update`. It MUST be deleted.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `handle_onboarding_signal` MUST call `_apply_taste_update()` with place metadata and the correct gain so the taste vector moves on every onboarding signal.
- **FR-002**: `handle_recommendation_accepted` MUST fetch the place record by `place_id`, build metadata from it, and call `_apply_taste_update()` with `is_positive=True`.
- **FR-003**: `handle_recommendation_rejected` MUST fetch the place record by `place_id`, build metadata from it, and call `_apply_taste_update()` with `is_positive=False`.
- **FR-004**: `upsert()` in `SQLAlchemyTasteModelRepository` MUST increment `interaction_count` and recompute `confidence` in a single atomic SQL UPDATE with no Python-side read of the prior count.
- **FR-005**: A new Alembic migration MUST add `ambiance` (String, nullable) to the `places` table.
- **FR-006**: The `Place` SQLAlchemy model MUST include `ambiance: Mapped[str | None]`.
- **FR-007**: `_place_to_metadata()` MUST return `price_range` (if set), `ambiance` (if set), and `time_of_day` (derived from `created_at`); fields not available MUST be omitted.
- **FR-008**: `taste_model_repository.py` MUST contain zero docstrings and zero inline comments.
- **FR-009**: `config/app.yaml` MUST use `#` (not `;`) for all comments.
- **FR-010**: All existing 84 tests MUST pass. `ruff check src/` and `mypy src/` MUST produce no new errors.
- **FR-011**: `_increment_and_update_confidence` MUST be deleted from `service.py` — it has no callers after Fixes 1–3 and dead code is not permitted.
- **FR-012**: The INSERT path in `upsert()` MUST use `ON CONFLICT (user_id) DO UPDATE SET interaction_count = taste_model.interaction_count + 1, confidence = ..., parameters = EXCLUDED.parameters` so concurrent first-interactions for a new user never produce a constraint violation.

### Key Entities

- **Place**: Gains nullable `ambiance` String field (one of: casual, moderate, upscale) used as the observation source for `ambiance_preference` taste dimension.
- **TasteModel**: `interaction_count` and `confidence` columns updated atomically per interaction via SQL expression, not Python arithmetic.
- **interaction_log**: No changes. Continues to be written before every taste vector update.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Saving a `price_range=high` place changes `price_comfort` in `taste_model.parameters` — the value after differs from 0.5 starting value.
- **SC-002**: An onboarding confirmation and an onboarding dismissal for the same place produce taste vectors that differ from each other in at least one dimension.
- **SC-003**: Accepting a recommendation produces a different `taste_model.parameters` than before the accept signal.
- **SC-004**: `interaction_count` increments by exactly 1 per `upsert()` call with no Python read of the current value in the critical path.
- **SC-005**: A place saved with `ambiance=upscale` causes `ambiance_preference` to increase; a place with `ambiance=null` causes no change to `ambiance_preference`.
- **SC-006**: A place saved at 21:30 UTC produces `time_of_day=dinner` in metadata and moves `time_of_day_preference` toward 0.66.
- **SC-007**: 84 existing tests pass. `ruff check src/` and `mypy src/` produce zero errors.

## Assumptions

- `time_of_day` derivation uses UTC hour from `place.created_at`. Timezone-aware bucketing (using lat/lng to determine local time) is deferred to Phase 4.
- `handle_recommendation_accepted` gain is 2.0 and `handle_recommendation_rejected` gain is −1.5 (matching config). The task description mentions 1.5 for rejected — this refers to the absolute value. The config value `rejected: -1.5` is used directly with `is_positive=False`.
- `_increment_and_update_confidence` is deleted after all three calling sites are migrated to `_apply_taste_update`.
- The new migration is the third Alembic migration in this feature branch, running after the two existing taste model migrations.
- `ambiance` values stored in the Place model must match the config lookup keys (`casual`, `moderate`, `upscale`) to produce non-neutral observations. The extraction pipeline mapping (GooglePlaces → ambiance string) is out of scope for this task.
- The 5 dimensions without observable place fields (crowd_level, dietary_pref, cuisine_frequency, cuisine_adventurousness, distance) intentionally default to 0.5. These require behavioral history or query-time data and are deferred to Phase 4.
