# Contract: POST /v1/consult

Source of truth: `docs/api-contract.md`. This file documents the Phase 2 implementation contract.

## Request

```json
{
  "user_id": "string (required)",
  "query": "string (required)",
  "location": {
    "lat": 13.7563,
    "lng": 100.5018
  }
}
```

`location` is optional. `stream` field is accepted but ignored for this contract (SSE mode is separate).

## Response (HTTP 200)

```json
{
  "primary": {
    "place_name": "Fuji Ramen",
    "address": "123 Sukhumvit Soi 33, Bangkok",
    "reasoning": "Your top-rated ramen spot for a date night.",
    "source": "discovered",
    "photos": ["https://placehold.co/800x450.webp"]
  },
  "alternatives": [
    {
      "place_name": "Bankara Ramen",
      "address": "456 Sukhumvit Soi 39, Bangkok",
      "reasoning": "Known for rich tonkotsu broth.",
      "source": "discovered",
      "photos": ["https://placehold.co/800x450.webp"]
    }
  ],
  "reasoning_steps": [
    { "step": "intent_parsing", "summary": "Parsed: cuisine=ramen, occasion=date night" },
    { "step": "retrieval",      "summary": "Looking for ramen places you've saved near Sukhumvit" },
    { "step": "discovery",      "summary": "Searching for ramen restaurants within 1.2km of your location" },
    { "step": "validation",     "summary": "Checking which ramen spots are open now" },
    { "step": "ranking",        "summary": "Comparing ramen options for a date night" },
    { "step": "completion",     "summary": "Found your match" }
  ]
}
```

## Error Responses

| Status | Trigger | Body |
|--------|---------|------|
| 400 | `query` empty or missing | `{"error_type": "bad_request", "detail": "..."}` |
| 422 | LLM output fails schema validation | FastAPI default 422 body |
| 500 | Unexpected internal failure | `{"error_type": "internal_error", "detail": "..."}` |

## Phase 2 Constraints

- `source` is always `"discovered"` (no pgvector retrieval yet)
- `alternatives` always contains exactly 2 entries
- `photos` uses placeholder URL `https://placehold.co/800x450.webp`
- All 6 step summaries use intent-derived values; no phase/deferral language ever appears
- Null intent fields use fallbacks: cuisine → "restaurants", location → "nearby", occasion → "your criteria", radius → 1.2km
