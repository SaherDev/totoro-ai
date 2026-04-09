# Data Model: Chat Assistant Service

**Feature**: 016-chat-assistant-service  
**Date**: 2026-04-09

## Entities

### ChatRequest

API request body. Validated at the FastAPI boundary (Pydantic, ADR-017).

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `user_id` | `str` | required, non-empty | Caller identity; passed to Langfuse for tracing |
| `message` | `str` | required, `min_length=1` | The user's question or request |

Validation: Pydantic rejects missing or empty `message` with HTTP 422 automatically. No service-layer validation needed.

---

### ChatResponse

API response body.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `response` | `str` | non-empty | The assistant's conversational answer |

---

## State & Lifecycle

**Stateless.** No entities are persisted. No database tables read or written. No Redis keys created. Each request is fully independent.

## No new database entities

This feature introduces no new SQLAlchemy models, Alembic migrations, or pgvector operations. The boundary is: `ChatRequest` in → `ChatResponse` out.
