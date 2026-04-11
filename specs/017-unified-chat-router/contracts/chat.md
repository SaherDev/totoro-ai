# API Contract: POST /v1/chat

**Replaces**: `POST /v1/extract-place`, `POST /v1/consult`, `POST /v1/recall`, `POST /v1/chat-assistant`

---

## Endpoint

```
POST /v1/chat
Content-Type: application/json
```

---

## Request

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

---

## Response

```json
{
  "type": "consult",
  "message": "Based on what I know about you, try Nara Eatery…",
  "data": { /* ConsultResponse payload */ }
}
```

| Field | Type | Notes |
|---|---|---|
| `type` | `string` | One of: `extract-place`, `consult`, `recall`, `assistant`, `clarification`, `error` |
| `message` | `string` | Human-readable response text |
| `data` | `object \| null` | Structured payload from downstream service; null for clarification/assistant/error |

---

## Response Types by Intent

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

---

## HTTP Status Codes

| Code | When |
|---|---|
| `200` | All successful responses including clarification |
| `400` | Malformed request body |
| `422` | Validation error (FastAPI auto, per ADR-023) |
| `500` | Unhandled internal error |

---

## Removed Endpoints

The following endpoints return `404` after this feature ships:

| Endpoint | Replaced by |
|---|---|
| `POST /v1/extract-place` | `POST /v1/chat` with extract-place intent |
| `GET /v1/extract-place/status/{id}` | Deferred — status polling for provisional extractions not yet in scope for /v1/chat |
| `POST /v1/consult` | `POST /v1/chat` with consult intent |
| `POST /v1/recall` | `POST /v1/chat` with recall intent |
| `POST /v1/chat-assistant` | `POST /v1/chat` with assistant intent |

> **Note on status polling**: `GET /v1/extract-place/status/{id}` (ADR-048) is currently not in scope for /v1/chat. It will need to be re-introduced separately if provisional extraction results are required.
