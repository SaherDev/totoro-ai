# API Contract: POST /v1/consult (Phase 3)

**Endpoint**: `POST /v1/consult`
**Auth**: Handled upstream by NestJS — `user_id` injected in request body.
**Response format**: Synchronous JSON only. SSE streaming removed for this phase.

---

## Request

```json
{
  "user_id": "string",
  "query": "string (natural language recommendation request)",
  "location": {
    "lat": 13.7563,
    "lng": 100.5018
  }
}
```

- `user_id` — required
- `query` — required, natural language
- `location` — optional; omit when query names a destination ("in Tokyo") or when no
  location context is needed

**Removed fields** (Phase 3):
- `stream` — removed; only synchronous JSON is supported

---

## Response (HTTP 200)

```json
{
  "primary": {
    "place_name": "Sushi Saito",
    "address": "1-9-15 Nishiazabu, Minato, Tokyo",
    "reasoning": "Your top-saved Japanese spot, highly rated, within 1.2 km",
    "source": "saved",
    "photos": []
  },
  "alternatives": [
    {
      "place_name": "Sukiyabashi Jiro",
      "address": "Tsukamoto Sozan Bldg. B1F, 4 Chome-2-15 Ginza, Tokyo",
      "reasoning": "Iconic omakase, popular, 2.3 km away",
      "source": "discovered",
      "photos": []
    }
  ],
  "reasoning_steps": [
    { "step": "intent_parsing", "summary": "Parsed: cuisine=sushi, radius=2000m" },
    { "step": "retrieval", "summary": "Found 3 saved sushi places, 2 within radius" },
    { "step": "discovery", "summary": "Found 8 nearby sushi restaurants via Google Places" },
    { "step": "validation", "summary": "Validation skipped (no live constraints)" },
    { "step": "deduplication", "summary": "Removed 1 duplicate (already saved)" },
    { "step": "ranking", "summary": "Ranked 9 candidates; top 3 selected" }
  ]
}
```

### PlaceResult fields

| Field       | Type           | Notes                                      |
|-------------|----------------|--------------------------------------------|
| place_name  | string         | —                                          |
| address     | string         | —                                          |
| reasoning   | string         | Derived from candidate data, no LLM call   |
| source      | "saved" \| "discovered" | —                             |
| photos      | list[string]   | May be empty (`[]`)                        |

### ConsultResponse fields

| Field           | Type                   | Notes                                |
|-----------------|------------------------|--------------------------------------|
| primary         | PlaceResult            | Highest-ranked candidate             |
| alternatives    | list[PlaceResult]      | Up to 2 further candidates           |
| reasoning_steps | list[ReasoningStep]    | One per pipeline step actually run   |

---

## Error Responses

| Status | Trigger                               | Body                                 |
|--------|---------------------------------------|--------------------------------------|
| 400    | Malformed request body                | `{"detail": "..."}`                  |
| 422    | Pydantic validation failure           | FastAPI default 422                  |
| 500    | Intent parser failure (LLM/timeout)   | `{"detail": "Intent parsing failed"}`|

External places provider failure (Step 3) does **not** return an error — the pipeline
falls back gracefully and returns only saved candidates.

---

## Changes from previous version

| Change                        | Before               | After             |
|-------------------------------|----------------------|-------------------|
| `stream` field on request     | `bool = False`       | removed           |
| `photos` field on PlaceResult | `list[str]` min 1    | `list[str] = []`  |
| Response generation           | LLM call             | Deterministic from candidate data |
| reasoning_steps content       | Static placeholders  | Reflects actual pipeline execution |
