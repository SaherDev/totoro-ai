# Data Model: Streaming Recommendations via SSE

**Branch**: `001-consult-streaming` | **Date**: 2026-03-17

---

## Entities

### ConsultRequest

Extends the existing consult request schema with an optional `stream` flag.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | string | yes | Caller's user identifier injected by NestJS |
| `query` | string | yes | Natural language recommendation query |
| `location` | Location | no | User's current latitude/longitude |
| `stream` | boolean | no | If `true`, returns SSE stream. Default: `false` |

### Location

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `lat` | float | yes | Latitude |
| `lng` | float | yes | Longitude |

### SyncConsultResponse (existing, synchronous mode)

| Field | Type | Description |
|-------|------|-------------|
| `primary` | PlaceResult | Top recommendation |
| `alternatives` | PlaceResult[] | Up to 2 alternatives |
| `reasoning_steps` | ReasoningStep[] | Agent steps for observability |

### PlaceResult

| Field | Type | Description |
|-------|------|-------------|
| `place_name` | string | Name of the place |
| `address` | string | Physical address |
| `reasoning` | string | Why this place was recommended |
| `source` | "saved" \| "discovered" | Whether from user's collection or external |

### ReasoningStep

| Field | Type | Description |
|-------|------|-------------|
| `step` | string | Step identifier (e.g., "intent_parsing") |
| `summary` | string | Human-readable description of what happened |

### SSE StreamEvent (streaming mode)

Two event types emitted during a streaming response:

**Token event** (one per AI-generated token):
```json
{"token": "Hello"}
{"token": " there"}
{"token": "!"}
```

**Done event** (single, final — signals stream end):
```json
{"done": true}
```

---

## Schema Notes

- `ConsultRequest.stream` defaults to `false` if absent — no breaking change to existing callers.
- The SSE event format uses `data: {json}\n\n` per the SSE specification (RFC 8895).
- Token events are emitted one-per-token as the AI generates them — no buffering.
- The done event (`{"done": true}`) is the stream terminator; clients should stop reading after it.
- Phase 1 uses a hardcoded system prompt; token content comes from the real AI provider.

---

## No New DB Tables

This feature does not introduce new database tables. The streaming mode is a transport change — no data persistence for Phase 1. Phase 4 will add intent parsing and ranking before calling the AI.
