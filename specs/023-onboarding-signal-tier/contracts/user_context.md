# Contract: GET /v1/user/context (extended)

No LLM call. Single DB round-trip: reads `taste_model` row and derives `signal_tier`.

---

## Request

```
GET /v1/user/context?user_id=user_abc
```

### Query parameters

| Name | Type | Required | Description |
|---|---|---|---|
| `user_id` | string | yes | User identifier |

---

## Response — 200 OK

### Cold user (no taste model row)

```json
{
  "user_id": "user_abc",
  "saved_places_count": 0,
  "signal_tier": "cold",
  "chips": []
}
```

### Warming user

```json
{
  "user_id": "user_abc",
  "saved_places_count": 3,
  "signal_tier": "warming",
  "chips": [
    {
      "label": "Early signal: cafe",
      "source_field": "subcategory.food_and_drink",
      "source_value": "cafe",
      "signal_count": 3,
      "status": "pending",
      "selection_round": null
    }
  ]
}
```

### Chip selection tier

```json
{
  "user_id": "user_abc",
  "saved_places_count": 5,
  "signal_tier": "chip_selection",
  "chips": [
    {
      "label": "Finds places on TikTok",
      "source_field": "source",
      "source_value": "tiktok",
      "signal_count": 5,
      "status": "pending",
      "selection_round": null
    },
    {
      "label": "Ramen lover",
      "source_field": "attributes.cuisine",
      "source_value": "ramen",
      "signal_count": 3,
      "status": "pending",
      "selection_round": null
    }
  ]
}
```

### Active user (mix of confirmed, rejected, pending)

```json
{
  "user_id": "user_abc",
  "saved_places_count": 12,
  "signal_tier": "active",
  "chips": [
    {
      "label": "Finds places on TikTok",
      "source_field": "source",
      "source_value": "tiktok",
      "signal_count": 9,
      "status": "confirmed",
      "selection_round": "round_1"
    },
    {
      "label": "Ramen lover",
      "source_field": "attributes.cuisine",
      "source_value": "ramen",
      "signal_count": 5,
      "status": "confirmed",
      "selection_round": "round_1"
    },
    {
      "label": "Casual spots",
      "source_field": "attributes.vibe",
      "source_value": "casual",
      "signal_count": 2,
      "status": "rejected",
      "selection_round": "round_1"
    }
  ]
}
```

---

## Server-side derivation

1. `profile = TasteModelService.get_taste_profile(user_id)` — single DB read from `taste_model`.
2. `signal_count = profile.generated_from_log_count` if profile exists, else `0`.
3. `signal_tier = derive_signal_tier(signal_count, profile.chips, stages, chip_threshold)`.
4. `current_sr = selection_round_name(signal_count, stages)` — highest-threshold crossed stage, or `None`.
5. `saved_places_count = profile.signal_counts["totals"].get("saves", 0)`.
6. Map each `Chip` to `ChipView`. For pending chips with `selection_round is None`, stamp `selection_round = current_sr` so the frontend sees a populated value. Confirmed/rejected chips keep their original round.

No LLM call. No Redis access. All data from one `taste_model` row.

The frontend echoes each chip's `selection_round` verbatim when building a `chip_confirm` submission.

---

## Errors

- `422` — missing `user_id`.
- `500` — DB connection failure. No logic path returns `404` — cold user gets an empty-chip `cold` response.
