# API Contract: Extraction Status Polling

## Updated: POST /v1/extract-place

**Change**: `request_id` field added to response for provisional extractions.

### Response (unchanged fields omitted)

```json
{
  "provisional": true,
  "places": [],
  "pending_levels": ["subtitle_check", "whisper_audio", "vision_frames"],
  "extraction_status": "processing",
  "source_url": "https://www.tiktok.com/...",
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

- `request_id` is a UUID4 string when `provisional: true`
- `request_id` is `null` (omitted) when `provisional: false`

---

## New: GET /v1/extract-place/status/{request_id}

### Request

```
GET /v1/extract-place/status/550e8400-e29b-41d4-a716-446655440000
```

**Path parameter**: `request_id` — the UUID4 returned in a provisional POST response.

**No request body. No auth headers (product repo handles auth).**

### Response: Processing (key absent or TTL expired)

**HTTP 200**

```json
{"extraction_status": "processing"}
```

### Response: Failed (background enrichers found nothing)

**HTTP 200**

```json
{"extraction_status": "failed"}
```

### Response: Complete (background extraction succeeded)

**HTTP 200**

```json
{
  "provisional": false,
  "places": [
    {
      "place_id": "abc123",
      "place_name": "Menya Musashi",
      "address": "123 Ramen St",
      "city": "Tokyo",
      "cuisine": "ramen",
      "confidence": 0.87,
      "resolved_by": "whisper_audio",
      "external_provider": "google_places",
      "external_id": "ChIJabc123"
    }
  ],
  "pending_levels": [],
  "extraction_status": "saved",
  "source_url": "https://www.tiktok.com/...",
  "request_id": null
}
```

### Error responses

| Status | Condition |
|--------|-----------|
| 200 | Always — unknown `request_id` returns `{"extraction_status": "processing"}` |

> **Note**: The status endpoint never returns 4xx or 5xx for unknown/expired IDs. Returning 404 would require the product repo to distinguish 404 (ID unknown) from 200+processing — unnecessary complexity at this stage.
