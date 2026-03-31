# Phase 0 Research: Taste Model Audit Fixes

**Branch**: `009-taste-model-audit-fixes` | **Date**: 2026-03-31

## No NEEDS CLARIFICATION Items

All technical unknowns were resolved during `/speckit.clarify`. This research document records the decisions made for each fix.

---

## Decision 1: ON CONFLICT for Concurrent New-User INSERT

**Question**: When two simultaneous signals arrive for a brand-new user, both see `rowcount=0` and both attempt an INSERT. How to prevent a unique constraint violation on `user_id`?

**Decision**: Use PostgreSQL `INSERT ... ON CONFLICT (user_id) DO UPDATE SET ...` (atomic upsert).

**Rationale**: The conflict target `(user_id)` is the unique constraint. When two concurrent INSERTs collide, the second one becomes an UPDATE. This avoids an unhandled `IntegrityError` while preserving atomic semantics. The alternative — catching the exception and retrying — introduces retry logic and is non-atomic.

**Alternatives considered**:
- Advisory lock around INSERT: serializes all first-time interactions for a user; higher latency, unnecessary for this case.
- Try/except + retry: adds complexity, not atomic.
- SELECT FOR UPDATE before INSERT: still requires explicit locking and two round trips.

**Implementation**: Use SQLAlchemy `insert(...).on_conflict_do_update(index_elements=["user_id"], ...)` from `sqlalchemy.dialects.postgresql`.

---

## Decision 2: Delete `_increment_and_update_confidence` Entirely

**Question**: Should `_increment_and_update_confidence` be deleted or left as dead code?

**Decision**: Delete entirely (FR-011).

**Rationale**: Dead code is not permitted per project standards. After all three handlers (`handle_onboarding_signal`, `handle_recommendation_accepted`, `handle_recommendation_rejected`) are migrated to `_apply_taste_update`, the method has zero callers.

---

## Decision 3: time_of_day Bucket Derivation

**Question**: What UTC hour boundaries define the four time-of-day buckets?

**Decision**: Use UTC hour from `place.created_at` with these boundaries:
- `breakfast`: hours 5–10 (5 AM to 10:59 AM)
- `lunch`: hours 11–14 (11 AM to 2:59 PM)
- `dinner`: hours 15–20 (3 PM to 8:59 PM)
- `late_night`: hours 21–4 (9 PM to 4:59 AM, wraps midnight)

**Rationale**: These map to `config/app.yaml` `taste_model.observations.time_of_day_preference` keys. Timezone-aware bucketing (using lat/lng for local time) is deferred — UTC is sufficient for Phase 3 behavior.

**Implementation**: `place.created_at.hour` — SQLAlchemy `DateTime(timezone=True)` stores UTC; Python `.hour` on a UTC-aware datetime gives UTC hour.

---

## Decision 4: `ambiance` Field Type and Allowed Values

**Question**: What type and allowed values for the new `ambiance` field on `Place`?

**Decision**: `String`, nullable, no enum constraint at the database level. Values must match config lookup keys: `casual`, `moderate`, `upscale`.

**Rationale**: Enforcing an enum at DB level would require another migration if values are added. The config lookup table (`app.yaml`) already enforces valid values implicitly — an unrecognized string produces `0.5` (neutral observation) via `_get_observation_value`. The extraction pipeline mapping (Google Places → ambiance string) is out of scope; the field stores whatever the pipeline writes.

**Alembic migration**: `op.add_column("places", sa.Column("ambiance", sa.String(), nullable=True))`. Existing rows get `NULL` automatically.

---

## Decision 5: Docstring Removal Scope

**Question**: Which files need docstrings/comments removed?

**Decision**: Only `taste_model_repository.py` (FR-008). `service.py` was already cleaned in branch 008. `place_repository.py` is out of scope.

**Rationale**: FR-008 is scoped to `taste_model_repository.py`. The project standard (zero docstrings, zero inline comments) applies to all Python files, but the audit fix only targets the file that still has them after branch 008 work.

---

## Decision 6: YAML Comment Fix Scope

**Question**: Is `;` still present in `config/app.yaml`?

**Decision**: Verify during implementation. The editor auto-corrected `;` to `#` on branch 008. FR-009 requires `#` everywhere under `taste_model.observations`. A verification pass is sufficient; no edits needed if already correct.

---

## No New External Dependencies

All fixes use existing imports:
- `sqlalchemy.dialects.postgresql.insert` — already in pyproject.toml via `sqlalchemy`
- `math.exp` — stdlib
- `datetime` — stdlib

No new packages required.
