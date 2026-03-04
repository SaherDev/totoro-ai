# API Contract

HTTP contract between the product repo (`totoro`) and this AI repo (`totoro-ai`). All endpoints are under the `/v1/` prefix.

All requests come from NestJS after auth verification. This repo never receives requests directly from the frontend.

---

## POST /v1/extract-place

Extract structured place data from raw user input. FastAPI parses the input, validates via Google Places API, and generates an embedding vector. NestJS writes both the place record and the embedding to PostgreSQL.

**Request:**
```json
{
  "user_id": "string",
  "raw_input": "https://www.tiktok.com/@foodie/video/123 amazing ramen shop"
}
```

**Response:**
```json
{
  "place": {
    "place_name": "Fuji Ramen",
    "address": "123 Sukhumvit Soi 33, Bangkok",
    "cuisine": "ramen",
    "price_range": "low",
    "source_url": "https://www.tiktok.com/@foodie/video/123"
  },
  "embedding": [0.012, -0.034, 0.056, "..."],
  "confidence": 0.92
}
```

**Notes:**
- `raw_input` accepts any format: URLs (TikTok, Instagram, blog), plain place names, or free descriptions like "that ramen shop near Sukhumvit."
- If the input is a URL, FastAPI fetches and parses the page content.
- If the input is a name or description, FastAPI validates against Google Places API.
- `confidence` indicates extraction certainty. Below 0.5, the product repo should ask the user to confirm.
- `embedding` is the vector representation for pgvector storage. NestJS writes this to PostgreSQL.
- `source_url` is `null` when the input is not a URL.
- Fields like `cuisine` and `price_range` may be `null` if extraction cannot determine them.

---

## POST /v1/consult

Recommend a place. FastAPI runs the full LangGraph agent pipeline autonomously: parse intent, retrieve saved places via pgvector (direct read), discover external candidates via Google Places API, validate, rank, and generate a response.

**Request:**
```json
{
  "user_id": "string",
  "query": "Find me a cozy ramen place near Sukhumvit for a date night",
  "location": {
    "lat": 13.7563,
    "lng": 100.5018
  }
}
```

**Response:**
```json
{
  "primary": {
    "place_name": "Fuji Ramen",
    "address": "123 Sukhumvit Soi 33, Bangkok",
    "reasoning": "Matches your preference for cozy ramen spots. You saved this after your last visit.",
    "source": "saved"
  },
  "alternatives": [
    {
      "place_name": "Mensho Tokyo",
      "address": "456 Thonglor Soi 10, Bangkok",
      "reasoning": "Highly rated ramen in a nearby area, good date atmosphere.",
      "source": "discovered"
    }
  ]
}
```

**Notes:**
- The agent runs the full pipeline internally. No mid-pipeline callbacks to NestJS.
- `source` is `"saved"` for places from the user's collection, `"discovered"` for external candidates found via Google Places API.
- Returns 1 primary recommendation + up to 2 alternatives with reasoning.
- NestJS persists the recommendation and streams the response to the frontend.

---

## General Notes

- All requests include `user_id` so FastAPI can load user-specific taste models and saved places.
- Response fields like `distance`, `price`, `open_status`, and `photos` will be added in later phases.
- The product repo is responsible for auth and validating `user_id` before calling these endpoints.
