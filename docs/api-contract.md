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

## POST /v1/extract-place

Extract and validate a place from raw user input. FastAPI parses the input, validates via Google Places API, generates an embedding, and writes both the place record and embedding to PostgreSQL directly. NestJS receives a confirmation, not raw data to persist.

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
  "place_id": "string",
  "place": {
    "place_name": "Fuji Ramen",
    "address": "123 Sukhumvit Soi 33, Bangkok",
    "cuisine": "ramen",
    "price_range": "low",
    "source_url": "https://www.tiktok.com/@foodie/video/123"
  },
  "confidence": 0.92
}
```

**Notes:**

- `raw_input` accepts any format: URLs (TikTok, Instagram, blog), plain place names, or free descriptions like "that ramen shop near Sukhumvit."
- If the input is a URL, FastAPI fetches and parses the page content.
- If the input is a name or description, FastAPI validates against Google Places API.
- FastAPI writes the place record and embedding to PostgreSQL. The response does not include the embedding vector.
- `place_id` is the database ID of the newly created place record.
- `confidence` indicates extraction certainty. Below 0.5, the product repo should ask the user to confirm.
- `source_url` is `null` when the input is not a URL.
- `cuisine` and `price_range` may be `null` if extraction cannot determine them.
- The response schema will evolve. Treat unknown fields as forward-compatible. Do not fail on extra keys.

---

## POST /v1/consult

Recommend a place. FastAPI runs the full LangGraph agent pipeline autonomously: parse intent, retrieve saved places via pgvector, discover external candidates via Google Places API, validate, rank, and generate a response.

**Request:**

```json
{
  "user_id": "string",
  "query": "good ramen near Sukhumvit for a date night",
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
    "reasoning": "Your top-rated ramen spot, 10 minutes from you, and perfect for a quiet dinner.",
    "source": "saved"
  },
  "alternatives": [
    {
      "place_name": "Bankara Ramen",
      "address": "456 Sukhumvit Soi 39, Bangkok",
      "reasoning": "Known for rich tonkotsu broth. You haven't tried it yet but it matches your preferences.",
      "source": "discovered"
    }
  ]
}
```

**Notes:**

- `query` is the raw user input, unmodified.
- `location` is the user's current location (optional, used for distance-aware ranking).
- Returns exactly 1 `primary` and up to 2 `alternatives`.
- Each result contains four core fields: `place_name`, `address`, `reasoning`, `source`.
- `source` is `"saved"` (from user's collection) or `"discovered"` (external lookup via Google Places).
- NestJS stores the recommendation in the recommendations table for history and analytics.
- One HTTP call. The agent runs autonomously. No mid-pipeline callbacks to NestJS.
- Additional fields (distance, price, open_status, confidence, photos) will be added in later phases. Design DTOs to tolerate extra fields.

---

## Error Handling

The AI service returns standard HTTP status codes:

| Status  | Meaning                              | Product repo action                                     |
| ------- | ------------------------------------ | ------------------------------------------------------- |
| 200     | Success                              | Process response                                        |
| 400     | Bad request (malformed input)        | Log error, return 400 to frontend                       |
| 422     | Could not parse intent or no results | Return friendly "couldn't understand" message           |
| 500     | AI service internal error            | Log error, return 503 to frontend with retry suggestion |
| Timeout | Service unreachable                  | Return 503 with "service temporarily unavailable"       |

**Timeout policy:** Set HTTP client timeout to 30 seconds for all AI service calls. extract-place should respond within 10s. consult may take up to 20s for complex queries.

---

## Shared Configuration

These values must stay in sync between both repos. A mismatch breaks the system.

**Embedding dimensions:**

- Current: 1536 (OpenAI text-embedding-3-small)
- The pgvector column definition in Prisma (product repo) must match the embedding model output in FastAPI (AI repo)
- If the embedding model changes, both the Prisma migration and FastAPI config must update together

**Database tables FastAPI writes to:**

- places
- embeddings
- taste_model

If Prisma changes the schema of these tables, FastAPI must adapt. Coordinate schema changes before running migrations.

---

## General Notes

- All requests include `user_id` so FastAPI can load user-specific taste models and saved places.
- FastAPI writes AI-generated data (places, embeddings, taste model) directly to PostgreSQL.
- NestJS writes product data (users, settings, recommendation history) to PostgreSQL.
- Neither service writes to the other's tables.
- The product repo is responsible for auth and validating `user_id` before calling these endpoints.
