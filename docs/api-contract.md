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

Extract and validate a place from raw user input (ADR-017, ADR-018). Accepts TikTok URLs (with optional descriptive text), plain text descriptions, or mixed formats (text + URL in any order). Validates via Google Places API and returns either a saved place record or a candidate requiring user confirmation.

**Request:**

```json
{
  "user_id": "string",
  "raw_input": "https://www.tiktok.com/@foodie/video/123 amazing ramen shop"
}
```

Alternative formats:
```json
{
  "user_id": "string",
  "raw_input": "amazing ramen shop https://www.tiktok.com/@foodie/video/123"
}
```

```json
{
  "user_id": "string",
  "raw_input": "amazing ramen shop"
}
```

**Response (Saved — confidence ≥ 0.70):**

```json
{
  "place_id": "550e8400-e29b-41d4-a716-446655440000",
  "place": {
    "place_name": "Fuji Ramen",
    "address": "123 Sukhumvit Soi 33, Bangkok",
    "cuisine": "ramen",
    "price_range": "low"
  },
  "confidence": 0.90,
  "requires_confirmation": false,
  "source_url": "https://www.tiktok.com/@foodie/video/123"
}
```

**Response (Confirmation Required — 0.30 < confidence < 0.70):**

```json
{
  "place_id": null,
  "place": {
    "place_name": "Fuji Ramen",
    "address": "123 Sukhumvit Soi 33, Bangkok",
    "cuisine": null,
    "price_range": null
  },
  "confidence": 0.55,
  "requires_confirmation": true,
  "source_url": null
}
```

**Error Responses:**

| Status | Error Type | Trigger |
|--------|-----------|---------|
| 400 | `bad_request` | `raw_input` is empty |
| 422 | `unsupported_input` | Non-TikTok URL in Phase 2 |
| 422 | `extraction_failed_no_match` | Confidence ≤ 0.30 (no Places match) |
| 500 | `extraction_error` | TikTok oEmbed timeout, Places API failure, or DB write failure |

**Error Response Body:**

```json
{
  "error_type": "extraction_failed_no_match",
  "detail": "Could not identify place from input. Confidence too low."
}
```

**Notes:**

- **Input formats**: Supports TikTok URLs, plain text, and hybrid formats (URL + descriptive text in any order). Parser extracts URL and merges surrounding text as supplementary context.
- **Phase 2 support**: TikTok URLs, plain text, and hybrid inputs. Instagram/generic URLs are Phase 3.
- **Extraction**:
  - **TikTok URLs**: System fetches the caption via oEmbed (3-second timeout), then merges any supplementary text from raw_input before LLM extraction. Example: "amazing ramen https://tiktok.com/.../123" → LLM sees "amazing ramen + oEmbed caption".
  - **Plain text**: Text is passed directly to the LLM.
  - **Hybrid (URL + text)**: Text before and after the URL is combined and passed to the LLM alongside the URL or caption.
- **Validation**: Extracted place name is validated against Google Places API. Match quality (EXACT, FUZZY, CATEGORY_ONLY, NONE) feeds into confidence scoring.
- **Confidence threshold**: ≥ 0.70 saves automatically; 0.30-0.70 requires user confirmation; ≤ 0.30 returns error.
- **Embeddings**: NOT generated in this endpoint (ADR-040). Embeddings are handled separately.
- **Deduplication**: If a `(external_provider, external_id)` match exists, the existing Place record is returned without a new write (ADR-041).
- **Timeout**: Total budget 10s; TikTok oEmbed timeout 3s; remaining budget covers LLM extraction and Places validation.
- `source_url`: Original TikTok URL (populated for TikTok input); `null` for plain text.
- `cuisine` and `price_range`: Nullable — may be `null` if LLM cannot determine them.
- The response schema tolerates extra fields (forward-compatible).

---

## POST /v1/consult

Recommend a place. FastAPI runs the full LangGraph agent pipeline autonomously: parse intent, retrieve saved places via pgvector, discover external candidates via Google Places API, validate, rank, and generate a response.

This endpoint has two response modes. The default mode returns a synchronous JSON response. A future SSE (Server-Sent Events) mode will stream agent reasoning steps in real time before the final response. The SSE mode will be added when the frontend needs to show the agent's thinking process. Until then, all clients use the synchronous mode.

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
  ],
  "reasoning_steps": [
    {
      "step": "intent_parsing",
      "summary": "Parsed: cuisine=ramen, occasion=date night, area=Sukhumvit"
    },
    {
      "step": "retrieval",
      "summary": "Found 3 saved ramen places near Sukhumvit"
    },
    {
      "step": "discovery",
      "summary": "Searching 38 restaurants within 1.2km"
    },
    {
      "step": "validation",
      "summary": "24 places open now"
    },
    {
      "step": "ranking",
      "summary": "Ranked 8 candidates by taste fit, distance, and occasion match"
    },
    {
      "step": "completion",
      "summary": "Found your match"
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
- `reasoning_steps` is an array of objects showing what the agent did at each stage. Each object has `step` (string identifier) and `summary` (human-readable description). Initially returned as part of the synchronous response. When SSE mode is added, these same steps will stream in real time before the final response. Step summaries must carry real counts from the pipeline, not generic text.
- `photos` is required. The primary recommendation card requires a full-width 16:9 hero photo URL. Each alternative requires a 1:1 square photo URL.
- Additional fields (distance, price, open_status, confidence) will be added as needed. Design DTOs to tolerate extra fields.

---

## POST /v1/recall

Retrieve saved places matching a natural language memory fragment. Only searches the user's collection — no external discovery.

**Request (Frontend → NestJS):**

```json
{
  "query": "that ramen place I saved from TikTok"
}
```

**Request (NestJS → totoro-ai):**

```json
{
  "user_id": "string",
  "query": "that ramen place I saved from TikTok"
}
```

**Response:**

```json
{
  "results": [
    {
      "place_id": "string",
      "place_name": "Fuji Ramen",
      "address": "123 Sukhumvit Soi 33, Bangkok",
      "cuisine": "ramen",
      "price_range": "low",
      "source_url": "https://www.tiktok.com/@foodie/video/123",
      "saved_at": "2026-02-12T14:30:00Z",
      "match_reason": "Saved from TikTok, tagged ramen"
    }
  ],
  "total": 1
}
```

**Notes:**

- `user_id` is injected by NestJS from the Clerk auth token. The frontend request body does NOT include `user_id`.
- `saved_at`: ISO 8601 timestamp when the user saved this place. Used to display provenance as "Saved from TikTok · Feb 12 · Bangkok".
- Phase 1: NestJS stub returns 501 Not Implemented. Phase 3 will forward to totoro-ai.
- Error handling follows the same table as `/v1/consult`.

---

## API Contract Summary

| Endpoint               | Purpose                                     | NestJS Sends             | totoro-ai Returns                          |
| ---------------------- | ------------------------------------------- | ------------------------ | ------------------------------------------ |
| POST /v1/extract-place | Extract and validate a place from raw input | raw_input, user_id       | place_id, place metadata, confidence score |
| POST /v1/consult       | Get a recommendation from natural language  | query, user_id, location | 1 primary + 2 alternatives with reasoning  |
| POST /v1/recall        | Retrieve saved places matching memory       | query, user_id           | list of saved places matching query        |

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

- Current: 1024 (Voyage 3.5-lite)
- The pgvector column definition in Prisma (product repo) must match the embedding model output in FastAPI (AI repo)
- If the embedding model changes, both the Prisma migration and FastAPI config must update together

**Database tables FastAPI writes to:**

- places
- embeddings
- taste_model

Alembic in totoro-ai owns migrations for these tables. Prisma never migrates these tables. If the schema changes, run the migration from totoro-ai only.

---

## General Notes

- All requests include `user_id` so FastAPI can load user-specific taste models and saved places.
- FastAPI writes AI-generated data (places, embeddings, taste model) directly to PostgreSQL.
- NestJS writes product data (users, settings, recommendation history) to PostgreSQL.
- Neither service writes to the other's tables.
- The product repo is responsible for auth and validating `user_id` before calling these endpoints.
