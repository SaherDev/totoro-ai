# Contract: POST /v1/consult (warming-tier blend only)

Feature 023 makes **no schema change** to `ConsultResponse`. The product repo
gates on `signal_tier` from `GET /v1/user/context` and does **not** call
`/v1/consult` at `cold` or `chip_selection` tiers. This contract therefore
covers only `warming` and `active` tier traffic, and the only behavioral
change is the warming-tier candidate mix.

---

## Request (unchanged)

```json
POST /v1/consult
Content-Type: application/json

{
  "user_id": "user_abc",
  "query": "where should I eat tonight?",
  "location": { "lat": 13.7563, "lng": 100.5018 }
}
```

---

## Response — 200 OK (unchanged shape)

```json
{
  "recommendation_id": "2f4e8a1b-3c5d-...",
  "results": [
    {
      "place": { "place_id": "...", "place_name": "...", "...": "..." },
      "source": "saved"
    }
  ],
  "reasoning_steps": [
    { "step": "intent", "summary": "..." }
  ]
}
```

No new fields. No `message_type` discriminator. No `pending_chips`. Those
exist on `/v1/user/context` instead, where the frontend reads them to decide
whether to show the consult UI at all.

---

## Tier gating lives in the product repo, not here

| Tier | Frontend behavior | `/v1/consult` called? |
|---|---|---|
| `cold` | Show onboarding copy. No chat input accepted for consult intent. | No |
| `warming` | Show chat UI. Consult runs with warming blend applied. | Yes |
| `chip_selection` | Show chip-selection UI. No chat input accepted for consult intent. | No |
| `active` | Show chat UI. Consult runs normally. | Yes |

If a rogue client still POSTs `/v1/consult` while the user is cold or
chip_selection, the endpoint runs the pipeline as-is — no server-side
rejection, no envelope discriminator. The frontend is the source of truth
for tier gating.

---

## Warming-tier behavior (the only feature-023 change here)

When the user's `signal_tier` is `warming` (derived inside
`ConsultService.consult` via `TasteModelService.get_user_context`), the
pipeline slices the deduped candidate set by a config-driven ratio:

- `saved_cap   = round(total_cap × warming_blend.saved)`     — default 2 of 10
- `discovered_cap = round(total_cap × warming_blend.discovered)` — default 8 of 10

Config: `config/app.yaml` → `taste_model.warming_blend` (`discovered: 0.8`,
`saved: 0.2`). Values must sum to 1.0 — enforced by a Pydantic
`model_validator`.

No ranking weights change — there is no ranker (ADR-058). The blend is
expressed purely as candidate-count caps before the existing saved-first
ordering.

A `reasoning_steps` entry is added:

```json
{ "step": "warming_blend", "summary": "discovered=8, saved=2" }
```

At `active` tier, no blend is applied and the step is omitted.

---

## Errors (unchanged)

- `400` — invalid request shape.
- `422` — Pydantic validation failure.
- `500` — downstream service failure.
- `NoMatchesError` is caught upstream by `ChatService._dispatch` and mapped
  to an assistant response, not a 5xx.
