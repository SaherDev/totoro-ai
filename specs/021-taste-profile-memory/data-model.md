# Data Model: Taste Profile & Memory Redesign

**Feature**: 021-taste-profile-memory | **Date**: 2026-04-17

## Entities

### Interaction (replaces InteractionLog)

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| id | BIGSERIAL | PK, autoincrement | Replaces UUID PK |
| user_id | TEXT | NOT NULL, indexed | |
| type | ENUM(InteractionType) | NOT NULL | save, accepted, rejected, onboarding_confirm, onboarding_dismiss |
| place_id | TEXT | NOT NULL, FK → places.id | Was nullable; null rows deleted in migration |
| created_at | TIMESTAMPTZ | NOT NULL, server default now() | |

**Indexes**:
- `ix_interactions_user_type` on `(user_id, type)` — query by user + interaction type
- `ix_interactions_user_created` on `(user_id, created_at)` — query by user ordered by time

**Dropped columns** (from InteractionLog):
- `gain` (float) — EMA multiplier, no longer needed
- `context` (JSONB) — carried metadata; onboarding_explicit rows mapped to confirm/dismiss before drop

**Enum migration** (InteractionType replaces SignalType):
- Kept: `save`, `accepted`, `rejected`
- Added: `onboarding_confirm`, `onboarding_dismiss`
- Removed: `ignored`, `repeat_visit`, `search_accepted`, `onboarding_explicit`

---

### TasteModel (reshaped)

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| user_id | TEXT | PK | Was `id` UUID PK with separate unique index on user_id |
| taste_profile_summary | JSONB | NOT NULL, default '[]' | List of SummaryLine objects |
| signal_counts | JSONB | NOT NULL, default '{}' | SignalCounts structured object |
| chips | JSONB | NOT NULL, default '[]' | List of Chip objects |
| generated_at | TIMESTAMPTZ | nullable | Timestamp of last regen |
| generated_from_log_count | INTEGER | NOT NULL, default 0 | Stale-summary guard |

**Dropped columns** (from old TasteModel):
- `id` (UUID PK) — replaced by user_id as PK
- `model_version` (TEXT) — EMA versioning, no longer needed
- `parameters` (JSONB) — 8-dimensional EMA vector
- `confidence` (FLOAT) — EMA confidence score
- `interaction_count` (INT) — replaced by generated_from_log_count
- `eval_score` (FLOAT) — evaluation metric
- `created_at`, `updated_at` (TIMESTAMPTZ) — replaced by generated_at

---

## Pydantic Models (Application Layer)

### InteractionRow

```
type: str                    # InteractionType value
place_type: str              # PlaceType enum value
subcategory: str | None      # validated subcategory or None
source: str | None           # PlaceSource enum value or None
tags: list[str]              # mirrors PlaceObject.tags
attributes: PlaceAttributes  # reuses PlaceAttributes from core/places/models.py
```

Hydrated from `interactions JOIN places` query. Repository converts SQLAlchemy Row → InteractionRow internally.

### SummaryLine

```
text: str          # 1-200 chars, human-readable pattern
signal_count: int  # must exist in signal_counts
source_field: str  # JSON path in signal_counts (e.g., "attributes.cuisine")
source_value: str | None  # value at that path (null for aggregate claims)
```

### Chip

```
label: str         # 1-30 chars, UI display label
source_field: str  # JSON path in signal_counts
source_value: str  # value at that path (always required, unlike SummaryLine)
signal_count: int  # must be >= 3
```

### TasteArtifacts (LLM output)

```
summary: list[SummaryLine]  # max 6
chips: list[Chip]           # max 8
```

### SignalCounts (aggregation output)

```
totals: TotalCounts
  saves: int
  accepted: int
  rejected: int
  onboarding_confirmed: int
  onboarding_dismissed: int
place_type: dict[str, int]
subcategory: dict[str, dict[str, int]]     # grouped by place_type
source: dict[str, int]                      # saves only
tags: dict[str, int]
attributes: AttributeCounts
  cuisine: dict[str, int]
  price_hint: dict[str, int]
  ambiance: dict[str, int]
  dietary: dict[str, int]
  good_for: dict[str, int]
  location_context: LocationContextCounts
    neighborhood: dict[str, int]
    city: dict[str, int]
    country: dict[str, int]
rejected: RejectedCounts
  subcategory: dict[str, dict[str, int]]
  attributes: AttributeCounts              # same shape as above
```

### TasteProfile (read model)

```
taste_profile_summary: list[SummaryLine]
signal_counts: dict[str, Any]
chips: list[Chip]
```

---

## Relationships

```
Interaction.place_id → places.id (FK, NOT NULL)
TasteModel.user_id — no FK to users (cross-repo boundary; users table owned by NestJS)
```

## State Transitions

### Interaction Lifecycle
- Created: append-only INSERT on save/accept/reject/onboarding signal
- Never updated or deleted after creation

### TasteModel Lifecycle
- Created: first regen after min_signals threshold (3 interactions)
- Updated: subsequent regens (full overwrite of signal_counts + summary + chips)
- Stale guard: skip regen if `generated_from_log_count == current interaction count`

### Regen Trigger Flow
```
User action → Domain event (PlaceSaved/RecommendationAccepted/etc.)
  → EventHandler.on_*() → TasteModelService.handle_signal()
    → INSERT interaction row
    → RegenDebouncer.schedule(user_id, delay=30s)
      → [debounce window expires]
      → TasteModelService._run_regen(user_id)
        → aggregate_signal_counts(interactions)
        → LLM call → TasteArtifacts
        → validate_grounded(artifacts, signal_counts)
        → upsert_regen(user_id, signal_counts, summary, chips, log_count)
```

## Aggregation Rules

| Interaction type | Feeds | Notes |
|-----------------|-------|-------|
| save | Main tree (place_type, subcategory, tags, attributes) + source | Source counted for saves only |
| accepted | Main tree (place_type, subcategory, tags, attributes) | No source tracking |
| rejected | Rejected branch (subcategory, attributes) | Separate from main tree |
| onboarding_confirm | Main tree (place_type, subcategory, tags, attributes) | Same as save, no source |
| onboarding_dismiss | Rejected branch (subcategory, attributes) | Same as rejected |
