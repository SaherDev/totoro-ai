# API Contracts: 022-recommendations-context-signals

**Date**: 2026-04-17

## Modified: POST /v1/chat (consult response)

ConsultResponse gains a `recommendation_id` field.

**Response (consult type) — updated:**

```json
{
  "type": "consult",
  "message": "Here's my top pick for dinner nearby",
  "data": {
    "recommendation_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "results": [
      {
        "place": { },
        "source": "saved"
      }
    ],
    "reasoning_steps": [
      { "step": "retrieval", "summary": "Found 3 saved places matching query" }
    ]
  }
}
```

| Field              | Type         | Notes                                         |
|--------------------|--------------|-----------------------------------------------|
| recommendation_id  | string/null  | UUID from recommendations table. Null if persist failed. |

---

## New: GET /v1/user/context

**Request:**

```
GET /v1/user/context?user_id=user_3AhqBhtLzKKlbKrjVNGTHro1o76
```

| Param    | Type   | Required | Notes                |
|----------|--------|----------|----------------------|
| user_id  | string | Yes      | Query parameter      |

**Response (200):**

```json
{
  "saved_places_count": 12,
  "chips": [
    {
      "label": "Japanese",
      "source_field": "subcategory",
      "source_value": "japanese",
      "signal_count": 5
    },
    {
      "label": "Thai",
      "source_field": "subcategory",
      "source_value": "thai",
      "signal_count": 3
    }
  ]
}
```

**Response (422):** Missing `user_id` query parameter.

**Response (cold start — no taste profile):**

```json
{
  "saved_places_count": 0,
  "chips": []
}
```

---

## New: POST /v1/signal (replaces POST /v1/feedback)

**Request:**

```json
{
  "signal_type": "recommendation_accepted",
  "user_id": "user_3AhqBhtLzKKlbKrjVNGTHro1o76",
  "recommendation_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "place_id": "google:ChIJN1t_tDeuEmsRUsoyG83frY4"
}
```

| Field             | Type   | Required | Notes                                              |
|-------------------|--------|----------|------------------------------------------------------|
| signal_type       | string | Yes      | `"recommendation_accepted"` or `"recommendation_rejected"` |
| user_id           | string | Yes      | Clerk-issued user ID                                 |
| recommendation_id | string | Yes      | Must exist in recommendations table                  |
| place_id          | string | Yes      | Trusted, not validated against places table           |

**Response (202):** Signal accepted.

```json
{
  "status": "accepted"
}
```

**Response (404):** `recommendation_id` not found.

```json
{
  "detail": "Recommendation not found"
}
```

**Response (422):** Unknown `signal_type`.

---

## Deleted: POST /v1/feedback

This endpoint is removed. Product repo must migrate to `POST /v1/signal`.
