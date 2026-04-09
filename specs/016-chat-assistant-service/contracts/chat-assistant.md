# API Contract: POST /v1/chat-assistant

**Feature**: 016-chat-assistant-service  
**Date**: 2026-04-09

## Endpoint

```
POST /v1/chat-assistant
Content-Type: application/json
```

## Request

```json
{
  "user_id": "string",
  "message": "string (min length: 1)"
}
```

### Field rules

| Field | Required | Validation |
|-------|----------|------------|
| `user_id` | Yes | Non-empty string |
| `message` | Yes | Non-empty string (`min_length=1`) |

## Response — 200 OK

```json
{
  "response": "string"
}
```

`response` is the assistant's conversational answer. Always a non-empty string.

## Error Responses

| Status | Condition | Body |
|--------|-----------|------|
| 422 | Missing or empty `message` / `user_id` | FastAPI default validation error body |
| 503 | LLM call failed or timed out | `{"error_type": "llm_unavailable", "detail": "<reason>"}` |
| 500 | Unhandled internal error | `{"error_type": "extraction_error", "detail": "Internal server error"}` |

## Caller

NestJS product repo only. Never called directly from the frontend.

## Example

**Request:**
```json
{
  "user_id": "user_abc123",
  "message": "What do you think about Tokyo for food?"
}
```

**Response:**
```json
{
  "response": "Tokyo is probably the best food city in the world, full stop. The variety is staggering — from three-Michelin-star kaiseki to ¥600 ramen at a standing counter — and the average quality floor is higher than almost anywhere else. If I had to pick a focus, go deep on ramen (try both Tokyo-style shoyu and a tonkotsu shop for contrast), eat at a proper izakaya at least once, and don't skip the depachika food halls in department store basements. Avoid anything with an English-only menu near Shibuya crossing."
}
```
