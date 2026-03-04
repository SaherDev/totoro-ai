# API Contract

HTTP contract between the product repo (`totoro`) and this AI repo (`totoro-ai`). All endpoints are under the `/v1/` prefix.

---

## POST /v1/parse-intent

Parse a raw user query into structured intent.

**Request:**
```json
{
  "user_id": "string",
  "query": "Find me a cozy ramen place near Sukhumvit for a date night"
}
```

**Response:**
```json
{
  "intent": {
    "cuisine": "ramen",
    "occasion": "date night",
    "location": "Sukhumvit",
    "constraints": ["cozy"]
  }
}
```

---

## POST /v1/retrieve

Retrieve candidate places matching a structured intent.

**Request:**
```json
{
  "user_id": "string",
  "intent": {
    "cuisine": "ramen",
    "occasion": "date night",
    "location": "Sukhumvit",
    "constraints": ["cozy"]
  }
}
```

**Response:**
```json
{
  "candidates": [
    {
      "place_name": "Fuji Ramen",
      "address": "123 Sukhumvit Soi 33, Bangkok",
      "source": "saved"
    }
  ]
}
```

---

## POST /v1/rank

Rank candidates and return one primary recommendation plus alternatives.

**Request:**
```json
{
  "user_id": "string",
  "candidates": [
    {
      "place_name": "Fuji Ramen",
      "address": "123 Sukhumvit Soi 33, Bangkok",
      "source": "saved"
    }
  ],
  "context": {
    "cuisine": "ramen",
    "occasion": "date night",
    "location": "Sukhumvit",
    "constraints": ["cozy"]
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

---

## POST /v1/extract-place

Extract structured place data from free-text input (URL, place name, or description).

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
  "confidence": 0.92
}
```

**Notes:**
- The `raw_input` field accepts any format: URLs (TikTok, Instagram, blog), plain place names, or free descriptions like "that ramen shop near Sukhumvit."
- If the input is a URL, the AI service fetches and parses the page content.
- If the input is a name or description, the service validates against Google Places API.
- `confidence` indicates how certain the extraction is. Below 0.5, the product repo should ask the user to confirm.
- `source_url` is `null` when the input is not a URL.
- Fields like `cuisine` and `price_range` may be `null` if extraction cannot determine them.

---

## General Notes

- All requests include `user_id` so the AI repo can load user-specific taste models and saved places.
- Response fields like `distance`, `price`, `open_status`, `confidence`, and `photos` will be added in later phases.
- The product repo is responsible for auth and validating `user_id` before calling these endpoints.
