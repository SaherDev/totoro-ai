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
  "saved_places_count": 12,
  "chips": [
    { "label": "Japanese", "source_field": "subcategory", "source_value": "japanese", "signal_count": 5 }
  ]
}
```

**Notes:**

- Cold start (no taste profile): returns `saved_places_count: 0`, `chips: []`.
- `saved_places_count` is read from the precomputed taste model, not a direct DB count.
- Missing `user_id` returns 422 (FastAPI auto-validation).

---

## POST /v1/signal

Behavioral signal endpoint for recommendation feedback (ADR-060). Replaces `POST /v1/feedback`.

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

**Response (202):** `{ "status": "accepted" }`

**Response (404):** `recommendation_id` not found in recommendations table.

**Response (422):** Unknown `signal_type`.

**Notes:**

- Handler runs as background task after HTTP 202 response (ADR-043).
- Append-only — duplicate signals for the same recommendation are accepted.
- `place_id` is not validated against the places table.

---

## GET /v1/health

Health check endpoint. Returns service status and database connectivity.

---

## API Contract Summary

| Endpoint | Purpose | NestJS Sends | totoro-ai Returns |
| --- | --- | --- | --- |
| POST /v1/chat | Unified conversational entry point | user_id, message, optional location | type, message, optional data payload |
| GET /v1/user/context | User taste context for product UI | user_id (query param) | saved_places_count, chips |
| POST /v1/signal | Recommendation feedback signal | signal_type, user_id, recommendation_id, place_id | status (202) |
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
