# API Contract: POST /v1/extract-place

**Branch**: `002-extract-place` | **Date**: 2026-03-24
**Source of truth**: `docs/api-contract.md` — update that file after this spec is approved.

---

## Endpoint

```
POST /v1/extract-place
Content-Type: application/json
```

---

## Request

```json
{
  "user_id": "string",
  "raw_input": "string"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `user_id` | string | yes | Validated by NestJS before calling this endpoint. Trusted as-is. |
| `raw_input` | string | yes | TikTok URL or plain text. Empty string → 400. |

---

## Response — Success (200)

### Saved silently (confidence ≥ 0.70)

```json
{
  "place_id": "550e8400-e29b-41d4-a716-446655440000",
  "place": {
    "place_name": "Fuji Ramen",
    "address": "Sukhumvit Soi 33, Bangkok 10110",
    "cuisine": "ramen",
    "price_range": "low"
  },
  "confidence": 0.90,
  "requires_confirmation": false,
  "source_url": "https://www.tiktok.com/@foodie/video/123"
}
```

### Confirmation required (0.30 < confidence < 0.70)

```json
{
  "place_id": null,
  "place": {
    "place_name": "Fuji Ramen",
    "address": "Sukhumvit Soi 33, Bangkok 10110",
    "cuisine": "ramen",
    "price_range": null
  },
  "confidence": 0.55,
  "requires_confirmation": true,
  "source_url": null
}
```

No record is written to the database. NestJS surfaces the candidate name to the user. If the user confirms or corrects, NestJS calls this endpoint again with the confirmed input.

---

## Response — Errors

| Status | Error type | Trigger | NestJS action |
|--------|-----------|---------|---------------|
| 400 | `bad_request` | `raw_input` is empty or whitespace | Show input validation error |
| 422 | `extraction_failed_no_match` | confidence ≤ 0.30 (no Places match) | Prompt user: "We couldn't identify the place. What's the name?" |
| 422 | `unsupported_input` | Non-TikTok URL submitted (Phase 2 only) | Show: "We only support TikTok links right now." |
| 500 | `extraction_error` | TikTok oEmbed timeout (>3s), Places API failure, DB write failure | Log error, return 503 to frontend with retry suggestion |

### Error response body

```json
{
  "error_type": "extraction_failed_no_match",
  "detail": "Could not identify place from input. Confidence too low."
}
```

---

## Field notes

- `place_id`: UUID string, the `id` column from the `places` table. `null` when `requires_confirmation: true`.
- `source_url`: The original TikTok URL, preserved in the response. `null` for plain text input.
- `cuisine` and `price_range`: nullable — may be absent if the LLM cannot determine them.
- `confidence`: float 0.0–0.95. Computed deterministically from extraction source + Places match quality. The LLM does not provide this value.
- `requires_confirmation`: **threshold is 0.70** (updated from the previous 0.50 in the original contract draft).

---

## Timeout

- Total response budget: **10 seconds** (SC-002)
- TikTok oEmbed call: **3-second timeout**
- Remaining ~7 seconds shared between LLM extraction and Google Places validation
