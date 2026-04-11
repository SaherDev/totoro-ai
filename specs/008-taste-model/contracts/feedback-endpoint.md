# Contract: POST /v1/feedback

**Caller**: NestJS (product repo)
**Purpose**: Receive recommendation acceptance/rejection signals and update the taste model.

---

## Request

```json
{
  "user_id": "string",
  "recommendation_id": "string",
  "place_id": "string",
  "signal": "accepted" | "rejected"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| user_id | string | Yes | Injected by NestJS from Clerk auth token |
| recommendation_id | string | Yes | ID of the recommendation being responded to |
| place_id | string | Yes | The place the user acted on (primary or alternative) |
| signal | enum | Yes | `"accepted"` or `"rejected"` |

---

## Response

**200 OK** — signal received and queued for processing:

```json
{
  "status": "received"
}
```

**400 Bad Request** — missing or invalid fields:

```json
{
  "error_type": "bad_request",
  "detail": "signal must be 'accepted' or 'rejected'"
}
```

---

## Behaviour

- The route handler dispatches either `RecommendationAccepted` or `RecommendationRejected` via the `EventDispatcher`.
- The taste model update runs as a background task after the HTTP 200 response is sent — it does not block the response.
- The route handler never calls `TasteModelService` directly. It only calls `event_dispatcher.dispatch(event)`.
- A background update failure is logged and traced via Langfuse. It does not produce a retried or failed HTTP response.

---

## Notes

- This endpoint is called by NestJS after the user taps a feedback affordance in the frontend. The frontend never calls this endpoint directly.
- `recommendation_id` is stored in `interaction_log.context` for traceability. It is not used for routing.
- Future signals (ignored, repeat_visit, search_accepted) will extend the `signal` enum when their triggers are built. The endpoint contract is forward-compatible — NestJS should tolerate additional enum values in the response without breaking.
