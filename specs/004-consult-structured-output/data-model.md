# Data Model: Consult Endpoint — Structured Output (Phase 2)

## Entities

### ParsedIntent

Extracted structured representation of the user's intent from a raw query. Lives in `core/intent/intent_parser.py`.

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `cuisine` | `str` | Yes | Cuisine type (e.g., "ramen", "sushi") |
| `occasion` | `str` | Yes | Context/occasion (e.g., "date night", "quick lunch") |
| `price_range` | `str` | Yes | "low", "mid", "high", or null |
| `radius` | `int` | Yes | Preferred radius in meters, or null |
| `constraints` | `list[str]` | No (default `[]`) | Dietary, access, or other requirements |

Validation: All optional except `constraints` (defaults to empty list). `price_range` should be one of the three values when set.

### ConsultRequest

API request body for `POST /v1/consult`. Lives in `api/schemas/consult.py`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | `str` | Yes | User identifier (injected by NestJS) |
| `query` | `str` | Yes | Raw natural language query |
| `location` | `Location` | No | User's current lat/lng |
| `stream` | `bool` | No (default `false`) | SSE streaming mode flag |

### Location (nested in ConsultRequest)

| Field | Type | Required |
|-------|------|----------|
| `lat` | `float` | Yes |
| `lng` | `float` | Yes |

### PlaceResult (used in ConsultResponse)

A single place recommendation. Lives in `api/schemas/consult.py`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `place_name` | `str` | Yes | Name of the place |
| `address` | `str` | Yes | Full address |
| `reasoning` | `str` | Yes | Human-readable explanation for the recommendation |
| `source` | `str` | Yes | `"saved"` or `"discovered"` |
| `photos` | `list[str]` | Yes (non-empty) | Photo URLs; min 1 required |

Validation: `photos` must have at least 1 item (`min_length=1`). No nullable fields.

### ReasoningStep

One step in the agent reasoning trace. Lives in `api/schemas/consult.py`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `step` | `str` | Yes | Step identifier (e.g., "intent_parsing") |
| `summary` | `str` | Yes | Human-readable summary with real data |

### ConsultResponse

API response body for `POST /v1/consult`. Lives in `api/schemas/consult.py`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `primary` | `PlaceResult` | Yes | The top recommendation |
| `alternatives` | `list[PlaceResult]` | Yes | 0–2 alternative recommendations |
| `reasoning_steps` | `list[ReasoningStep]` | Yes | Exactly 6 steps |

## Step Identifier Constraint

`reasoning_steps` must contain exactly these 6 identifiers in this order:

1. `intent_parsing`
2. `retrieval`
3. `discovery`
4. `validation`
5. `ranking`
6. `completion`

Phase 2 provides real data in `intent_parsing` and honest stub summaries for the remaining 5.

## No Database Writes

Phase 2 introduces no database operations. No new Alembic migrations needed. No new SQLAlchemy models.
