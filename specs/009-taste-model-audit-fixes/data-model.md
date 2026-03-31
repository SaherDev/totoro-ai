# Data Model: Taste Model Audit Fixes

**Branch**: `009-taste-model-audit-fixes` | **Date**: 2026-03-31

## Changed Entities

### Place (modified)

New nullable field added via Alembic migration.

| Field | Type | Nullable | Values | Source |
|-------|------|----------|--------|--------|
| `ambiance` | String | Yes | `casual`, `moderate`, `upscale` | New — set by extraction pipeline |

All existing fields unchanged. Existing rows get `NULL` for `ambiance`.

**Validation**: No DB-level enum. Invalid strings produce neutral observation (0.5) via config lookup. The constraint lives in the extraction pipeline (out of scope).

**SQLAlchemy mapping**:
```python
ambiance: Mapped[str | None] = mapped_column(String, nullable=True)
```

---

### TasteModel (upsert semantics changed — no schema change)

No column changes. The `interaction_count` and `confidence` columns already exist (added in migration `69cb7399`). The change is purely in how `upsert()` writes them.

**Before (read-modify-write)**:
- Python reads `interaction_count`, adds 1, writes back
- Race: two concurrent calls both read 5, both write 6

**After (atomic SQL + ON CONFLICT)**:
- UPDATE path: `interaction_count = interaction_count + 1` in SQL
- INSERT path: `INSERT ... ON CONFLICT (user_id) DO UPDATE SET interaction_count = taste_model.interaction_count + 1, ...`
- Concurrent first-time signals: second INSERT becomes an UPDATE, no constraint violation

**Confidence formula** (unchanged, moved to SQL):
```
confidence = 1 − exp(−(interaction_count + 1) / 10.0)
```

---

### InteractionLog (no changes)

Written before every taste vector update. No structural changes in this feature.

---

## Alembic Migration

**File**: `alembic/versions/<hash>_add_ambiance_to_places.py`

**Operations**:
```python
op.add_column("places", sa.Column("ambiance", sa.String(), nullable=True))
```

**Rollback**:
```python
op.drop_column("places", "ambiance")
```

**Ordering**: Third Alembic migration in this feature branch, after `69cb739a` and `69cb7399`.

---

## taste_model.observations Config (reference)

`_place_to_metadata()` returns keys that map to these config observation tables. No config changes needed — the tables already cover `ambiance` and `time_of_day`.

| Metadata key | Taste dimension | Config section |
|-------------|-----------------|---------------|
| `price_range` | `price_comfort` | `taste_model.observations.price_comfort` |
| `ambiance` | `ambiance_preference` | `taste_model.observations.ambiance_preference` |
| `time_of_day` | `time_of_day_preference` | `taste_model.observations.time_of_day_preference` |

All other 5 dimensions (`dietary_alignment`, `cuisine_frequency`, `crowd_tolerance`, `cuisine_adventurousness`, `distance_tolerance`) default to `0.5` — no place field available.
