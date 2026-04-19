# Contract: POST /v1/signal (extended)

Discriminated union on `signal_type`. Adds `chip_confirm` variant.

---

## Variant 1: recommendation_accepted / recommendation_rejected (unchanged)

### Request

```json
POST /v1/signal
Content-Type: application/json

{
  "signal_type": "recommendation_accepted",
  "user_id": "user_abc",
  "recommendation_id": "2f4e8a1b-3c5d-...",
  "place_id": "google:ChIJ..."
}
```

Discriminator values for this variant: `"recommendation_accepted"`, `"recommendation_rejected"`.

### Response — 202 Accepted

```json
{ "status": "accepted" }
```

### Errors

- `404` — `recommendation_id` not found in `recommendations` table (`RecommendationNotFoundError`).
- `422` — missing fields, invalid discriminator.

---

## Variant 2: chip_confirm (new)

### Request

```json
POST /v1/signal
Content-Type: application/json

{
  "signal_type": "chip_confirm",
  "user_id": "user_abc",
  "metadata": {
    "chips": [
      {
        "label": "Finds places on TikTok",
        "signal_count": 5,
        "source_field": "source",
        "source_value": "tiktok",
        "status": "confirmed",
        "selection_round": "round_1"
      },
      {
        "label": "Ramen lover",
        "signal_count": 3,
        "source_field": "attributes.cuisine",
        "source_value": "ramen",
        "status": "confirmed",
        "selection_round": "round_1"
      },
      {
        "label": "Bangkok regular",
        "signal_count": 3,
        "source_field": "attributes.location_context.city",
        "source_value": "Bangkok",
        "status": "rejected",
        "selection_round": "round_1"
      },
      {
        "label": "Casual spots",
        "signal_count": 2,
        "source_field": "attributes.ambiance",
        "source_value": "casual",
        "status": "rejected",
        "selection_round": "round_1"
      }
    ]
  }
}
```

### Handler steps (server-side)

1. Write `Interaction` row — `type=CHIP_CONFIRM`, `user_id=<request.user_id>`, `place_id=NULL`, `metadata=<request.metadata as dict>`.
2. For each chip in `metadata.chips`, merge into `taste_model.chips` by matching `(source_field, source_value)`:
   - Match found + existing `status == "confirmed"` → no-op (FR-006a).
   - Match found + existing `status` in {`pending`, `rejected`} → update `status` and `selection_round` to submitted values.
   - No match → ignore (edge case in spec — non-matching chip is a no-op; request still succeeds).
3. Persist the updated chips array to `taste_model.chips`.
4. Dispatch `ChipConfirmed(user_id=<user_id>)` via `EventDispatcher`.
5. Return 202.

### Response — 202 Accepted

```json
{ "status": "accepted" }
```

No waiting for the background `on_chip_confirmed` handler (fire-and-forget, ADR-043).

### Errors

- `422` — missing `metadata`, empty chips array, missing/empty per-chip `selection_round`, unknown `status` value, invalid discriminator.
- No `404` path — `chip_confirm` does not validate `recommendation_id` (it has none).

### Idempotency

Per spec FR-012a and clarification Q3 Option A: no deduplication. Two identical chip_confirm requests each:
- Write their own `Interaction` row.
- Dispatch their own `ChipConfirmed` event.
- Cause two runs of the rewrite handler. Handler is idempotent on unchanged state (produces the same summary twice).

---

## OpenAPI schema excerpt

```yaml
components:
  schemas:
    SignalRequest:
      oneOf:
        - $ref: '#/components/schemas/RecommendationSignalRequest'
        - $ref: '#/components/schemas/ChipConfirmSignalRequest'
      discriminator:
        propertyName: signal_type
        mapping:
          recommendation_accepted: '#/components/schemas/RecommendationSignalRequest'
          recommendation_rejected: '#/components/schemas/RecommendationSignalRequest'
          chip_confirm: '#/components/schemas/ChipConfirmSignalRequest'
```
