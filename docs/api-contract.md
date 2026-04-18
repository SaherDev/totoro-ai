# API Contract — totoro ↔ totoro-ai

Source of truth: totoro/docs/api-contract.md. Copy to totoro-ai/docs/ after any changes.

This document defines the HTTP contract between the product repo (services/api) and the AI service (totoro-ai). The product repo is the client. The AI repo is the server.

All requests come from NestJS after auth verification. totoro-ai never receives requests directly from the frontend.

## Connection

- Base URL loaded from YAML config: `ai_service.base_url`
- All endpoints are prefixed with `/v1/`
- All requests are JSON over HTTP (`Content-Type: application/json`)
- Auth between services is TBD (likely a shared secret header in later phases)

---

## POST /v1/chat

Unified conversational entry point (ADR-052). Replaces all four former individual endpoints.
The system classifies intent, dispatches to the correct pipeline, and returns a structured response.

**Request:**

```json
{
  "user_id": "user_3AhqBhtLzKKlbKrjVNGTHro1o76",
  "message": "cheap dinner nearby",
  "location": { "lat": 13.7563, "lng": 100.5018 }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `user_id` | `string` | Yes | Clerk-issued user ID; trusted, not validated here |
| `message` | `string` | Yes | Natural language message from the user |
| `location` | `{ lat: float, lng: float }` | No | Passed to consult pipeline only; ignored for all other intents |
| `signal_tier` | `"cold" \| "warming" \| "chip_selection" \| "active" \| null` | No | Tier hint from the product repo (ADR-061). Read from `GET /v1/user/context` and forwarded so consult can apply tier-aware behavior (warming candidate-count blend, active-tier rejected-chip filter). When `null`, consult defaults to `"active"`. At `cold` and `chip_selection` the product repo should not call `/v1/chat` with a consult-intent message at all — it renders onboarding / chip-selection UI directly from `/v1/user/context`. |

**Response:**

```json
{
  "type": "consult",
  "message": "Based on what I know about you, try Nara Eatery…",
  "data": { }
}
```

| Field | Type | Notes |
|---|---|---|
| `type` | `string` | One of: `extract-place`, `consult`, `recall`, `assistant`, `clarification`, `error` |
| `message` | `string` | Human-readable response text |
| `data` | `object \| null` | Structured payload from downstream service; null for clarification/assistant/error |

**Response Types by Intent:**

### `extract-place`
```json
{ "type": "extract-place", "message": "Saved: Nara Eatery, Bangkok", "data": { /* ExtractPlaceResponse */ } }
```

### `consult`
```json
{ "type": "consult", "message": "Here's my top pick for dinner nearby", "data": { /* ConsultResponse */ } }
```

### `recall`
```json
{ "type": "recall", "message": "Found 3 places matching your search", "data": { /* RecallResponse */ } }
```

### `assistant`
```json
{ "type": "assistant", "message": "Tipping is not expected in Japan…", "data": null }
```

### `clarification`
```json
{ "type": "clarification", "message": "Are you looking for a place called Fuji you saved, or a recommendation near there?", "data": null }
```

### `error`
```json
{ "type": "error", "message": "Something went wrong, try again", "data": { "detail": "..." } }
```

**HTTP Status Codes:**

| Code | When |
|---|---|
| `200` | All successful responses including clarification |
| `400` | Malformed request body |
| `422` | Validation error (FastAPI auto, per ADR-023) |
| `500` | Unhandled internal error |

**Notes:**

- `location` is only forwarded to `ConsultService.consult()` — all other intents ignore it.
- Confidence threshold for intent classification is 0.7. Messages below threshold return `type="clarification"`.
- All downstream exceptions are caught and returned as `type="error"` with HTTP 200 (not 5xx).
- Consult results are persisted to the `recommendations` table after a successful response (ADR-060). The response includes a `recommendation_id` (UUID) referencing the persisted row. Write failures are logged but do not fail the caller response — `recommendation_id` will be `null` in that case.

---

## GET /v1/user/context

Returns taste profile context for the product UI (ADR-060).

**Request:**

```
GET /v1/user/context?user_id=user_3AhqBhtLzKKlbKrjVNGTHro1o76
```

| Param | Type | Required | Notes |
|---|---|---|---|
| `user_id` | `string` | Yes | Query parameter |

**Response (200):**

```json
{
  "user_id": "user_3AhqBhtLzKKlbKrjVNGTHro1o76",
  "saved_places_count": 5,
  "signal_tier": "chip_selection",
  "chips": [
    {
      "label": "Ramen lover",
      "source_field": "attributes.cuisine",
      "source_value": "ramen",
      "signal_count": 3,
      "status": "pending",
      "selection_round": "round_1"
    },
    {
      "label": "Finds places on TikTok",
      "source_field": "source",
      "source_value": "tiktok",
      "signal_count": 4,
      "status": "pending",
      "selection_round": "round_1"
    }
  ]
}
```

Note: `selection_round` is always a string in `chip_selection` tier — the server stamps pending chips with the current crossed-stage name. The frontend copies each chip's `selection_round` verbatim into the `chip_confirm` submission; no separate `round` field needed.

| Field | Type | Notes |
|---|---|---|
| `user_id` | `string` | Echoed from the request |
| `saved_places_count` | `integer` | Total number of saves; read from precomputed taste_model (not a live DB count) |
| `signal_tier` | `"cold" \| "warming" \| "chip_selection" \| "active"` | Derived by `derive_signal_tier` (ADR-061). Config-driven — adding a new stage to `chip_selection_stages` works without code changes |
| `chips` | `ChipView[]` | Full structured chips; see shape below |

`ChipView` shape:

| Field | Type | Notes |
|---|---|---|
| `label` | `string` | Short display label |
| `source_field` | `string` | JSON path into signal_counts that surfaced the chip |
| `source_value` | `string` | Value at that path |
| `signal_count` | `integer` | Aggregate signal count |
| `status` | `"pending" \| "confirmed" \| "rejected"` | Lifecycle; defaults to `"pending"` until a `chip_confirm` signal lands |
| `selection_round` | `string \| null` | For confirmed/rejected chips: the round the user decided in. For still-pending chips: the round the frontend should submit the chip under (server stamps the current crossed-stage name). `null` only at cold/warming tiers where no stage has been crossed. |

**Notes:**

- Cold start (no taste profile): returns `saved_places_count: 0`, `signal_tier: "cold"`, `chips: []`.
- No LLM call. Single DB round-trip.
- **Tier gating lives in the product repo** (ADR-061). The product reads `signal_tier` and decides what UI to render — onboarding at `cold`, chip-selection at `chip_selection`, normal chat at `warming`/`active`. At the first two tiers the product should NOT call `/v1/chat` with a consult-intent message; `/v1/consult` is not short-circuited server-side.

---

## POST /v1/signal

Behavioral signal endpoint (ADR-060, ADR-061). Replaces `POST /v1/feedback`. Discriminated union on `signal_type`.

### Variant 1: `recommendation_accepted` / `recommendation_rejected`

**Request:**

```json
{
  "signal_type": "recommendation_accepted",
  "user_id": "user_3AhqBhtLzKKlbKrjVNGTHro1o76",
  "recommendation_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "place_id": "google:ChIJN1t_tDeuEmsRUsoyG83frY4"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `signal_type` | `string` | Yes | `"recommendation_accepted"` or `"recommendation_rejected"` |
| `user_id` | `string` | Yes | Clerk-issued user ID |
| `recommendation_id` | `string` | Yes | Must exist in recommendations table |
| `place_id` | `string` | Yes | Trusted, not validated against places table |

**Responses:** `202 { "status": "accepted" }`; `404` if recommendation_id unknown; `422` on schema errors.

### Variant 2: `chip_confirm` (feature 023)

**Request:**

```json
{
  "signal_type": "chip_confirm",
  "user_id": "user_3AhqBhtLzKKlbKrjVNGTHro1o76",
  "metadata": {
    "chips": [
      {
        "label": "Ramen lover",
        "signal_count": 3,
        "source_field": "attributes.cuisine",
        "source_value": "ramen",
        "status": "confirmed",
        "selection_round": "round_1"
      },
      {
        "label": "Casual spots",
        "signal_count": 2,
        "source_field": "attributes.ambiance",
        "source_value": "casual",
        "status": "rejected",
        "selection_round": "round_1"
      }
    ]
  }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `signal_type` | `"chip_confirm"` | Yes | Discriminator |
| `user_id` | `string` | Yes | Clerk-issued user ID |
| `metadata.chips[i].status` | `"confirmed" \| "rejected"` | Yes | `"pending"` is not a valid submission (user is making a decision) |
| `metadata.chips[i].selection_round` | `string` | Yes | Copied verbatim from the chip's `selection_round` in the `/v1/user/context` response |

The frontend just echoes each chip back with an updated `status`. No outer `round` field — each chip already carries its anchor round.

**Responses:** `202 { "status": "accepted" }`; `422` on empty chips array, missing `selection_round`, unknown `status` value, or unknown discriminator.

**Server-side handling** (ADR-061):

1. Write an `Interaction` row with `type=chip_confirm`, `metadata=<request.metadata>`.
2. Read current `taste_model.chips`, merge submitted statuses in (confirmed chips are never mutated; pending/rejected can be overwritten by the submission; chips in the submission that don't match any stored chip are silently ignored).
3. Persist the merged chips array back to `taste_model.chips`.
4. Dispatch `ChipConfirmed` → handler runs an immediate taste-profile rewrite (bypasses the debouncer).

**Notes:**

- Handler runs as background task after HTTP 202 (ADR-043).
- No deduplication (clarification Q3). Duplicate chip_confirm submissions (e.g. network retries) each write their own row and dispatch their own event; the rewrite handler is idempotent on unchanged state.

---

## GET /v1/health

Health check endpoint. Returns service status and database connectivity.

---

## API Contract Summary

| Endpoint | Purpose | NestJS Sends | totoro-ai Returns |
| --- | --- | --- | --- |
| POST /v1/chat | Unified conversational entry point | user_id, message, optional location | type, message, optional data payload |
| GET /v1/user/context | User taste context for product UI | user_id (query param) | user_id, saved_places_count, signal_tier, chips (each with status + selection_round) |
| POST /v1/signal | Recommendation feedback OR chip_confirm | Discriminated on `signal_type` — recommendation variant (recommendation_id + place_id) OR chip_confirm variant (metadata.chips[] with per-chip selection_round) | status (202) |
| GET /v1/health | Service health check | — | status, db connectivity |

---

## Error Handling

The AI service returns standard HTTP status codes:

| Status | Meaning | Product repo action |
| --- | --- | --- |
| 200 | Success (including clarification and error type responses) | Process response |
| 400 | Bad request (malformed input) | Log error, return 400 to frontend |
| 422 | Validation error | Return friendly message to frontend |
| 500 | AI service internal error | Log error, return 503 to frontend with retry suggestion |
| Timeout | Service unreachable | Return 503 with "service temporarily unavailable" |

**Timeout policy:** Set HTTP client timeout to 30 seconds for all AI service calls. /v1/chat responses targeting consult intent may take up to 20s for complex queries.

---

## Shared Configuration

These values must stay in sync between both repos. A mismatch breaks the system.

**Embedding dimensions:**

- Current: 1024 (Voyage 4-lite)
- pgvector columns are fully owned by this repo's Alembic migrations — NestJS never defines vector columns
- If the embedding model changes, only this repo's Alembic migration and config need updating

**Database tables FastAPI writes to:**

- places
- embeddings
- taste_model
- recommendations (ADR-060 — AI recommendation history, renamed from consult_logs)
- user_memories (personal facts extracted from chat messages)
- interaction_log (append-only behavioral signal log)

Alembic in totoro-ai owns migrations for these tables. NestJS never touches them. If the schema changes, run the migration from totoro-ai only.

---

## General Notes

- All requests include `user_id` so FastAPI can load user-specific taste models and saved places.
- FastAPI writes AI-generated data (places, embeddings, taste model, recommendations) directly to PostgreSQL.
- NestJS writes product data (users, settings) to PostgreSQL.
- Neither service writes to the other's tables.
- The product repo is responsible for auth and validating `user_id` before calling these endpoints.
