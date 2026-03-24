# Extract-Place Code Flow

## Overview

`POST /v1/extract-place` is a deterministic extraction pipeline that accepts raw input (TikTok URL or plain text) and returns either a saved place record (high confidence) or a candidate requiring user confirmation (mid-range confidence).

The pipeline is orchestrated by `ExtractionService`, which coordinates:
- Input validation
- Dispatcher routing to the correct extractor
- Google Places validation
- Confidence scoring
- Threshold-based decision logic
- Database deduplication and persistence

---

## Architecture Diagram

```
POST /v1/extract-place { raw_input, user_id }
    │
    ├─→ ExtractionService.run()
    │   │
    │   ├─→ [Step 1] Validate input
    │   │   └─ Raises ValueError if empty → 400 bad_request
    │   │
    │   ├─→ [Step 2] ExtractionDispatcher.dispatch()
    │   │   │
    │   │   ├─→ TikTok URL?
    │   │   │   └─→ TikTokExtractor
    │   │   │       ├─ Fetch caption via oEmbed API (3s timeout)
    │   │   │       └─ LLM extraction via InstructorClient
    │   │   │
    │   │   └─→ Plain text?
    │   │       └─→ PlainTextExtractor
    │   │           └─ LLM extraction via InstructorClient
    │   │
    │   ├─→ ExtractionResult { extraction, source, source_url }
    │   │
    │   ├─→ [Step 3] GooglePlacesClient.validate_place()
    │   │   ├─ Text Search API call (5s timeout)
    │   │   └─ PlacesMatchResult { match_quality, validated_name, place_id, lat, lng }
    │   │
    │   ├─→ [Step 4] compute_confidence()
    │   │   ├─ Base score from source
    │   │   ├─ Places modifier (EXACT/FUZZY/CATEGORY_ONLY/NONE)
    │   │   └─ Final score: 0.0-0.95
    │   │
    │   ├─→ [Step 5] Apply thresholds
    │   │   │
    │   │   ├─ confidence ≤ 0.30?
    │   │   │   └─ ExtractionFailedNoMatchError → 422 extraction_failed_no_match
    │   │   │
    │   │   ├─ 0.30 < confidence < 0.70?
    │   │   │   └─ ExtractPlaceResponse { place_id: null, requires_confirmation: true }
    │   │   │
    │   │   └─ confidence ≥ 0.70?
    │   │       │
    │   │       ├─→ [Step 6] Deduplication check
    │   │       │   └─ Query: SELECT * FROM places WHERE google_place_id = ?
    │   │       │       ├─ Found? Return existing place_id
    │   │       │       └─ Not found? Continue to Step 7
    │   │       │
    │   │       └─→ [Step 7] Persist new Place
    │   │           ├─ Create Place model
    │   │           ├─ db_session.add() + commit()
    │   │           └─ Return place_id
    │   │
    │   └─→ ExtractPlaceResponse
    │       ├─ place_id (if saved or deduplicated)
    │       ├─ place (extracted data)
    │       ├─ confidence (computed score)
    │       ├─ requires_confirmation (bool)
    │       └─ source_url (TikTok URL or null)
    │
    └─→ NestJS receives response
```

---

## Classes & Modules

### ExtractionService (`src/totoro_ai/core/extraction/service.py`)

Main orchestrator. Implements the full 7-step pipeline.

```python
class ExtractionService:
    def __init__(
        self,
        dispatcher: ExtractionDispatcher,
        places_client: PlacesClient,
        db_session_factory: Callable[[], AsyncSession],
    ) -> None: ...

    async def run(
        self, raw_input: str, user_id: str
    ) -> ExtractPlaceResponse: ...
```

**Steps:**
1. Validate `raw_input` not empty
2. Dispatch to extractor via dispatcher
3. Validate extracted place via GooglePlacesClient
4. Compute confidence score
5. Apply thresholds (decide action)
6. Check deduplication by `google_place_id`
7. Persist new Place to database

### ExtractionDispatcher (`src/totoro_ai/core/extraction/dispatcher.py`)

Routes raw input to the first extractor that `supports()` it. Priority order matters.

```python
class ExtractionDispatcher:
    def __init__(self, extractors: list[InputExtractor]) -> None: ...

    async def dispatch(self, raw_input: str) -> ExtractionResult | None:
        for extractor in self._extractors:
            if extractor.supports(raw_input):
                return await extractor.extract(raw_input)
        raise UnsupportedInputError(...)
```

### InputExtractor Protocol (`src/totoro_ai/core/extraction/protocols.py`)

All extractors implement this protocol.

```python
class InputExtractor(Protocol):
    async def extract(self, raw_input: str) -> ExtractionResult | None: ...
    def supports(self, raw_input: str) -> bool: ...
```

### TikTokExtractor (`src/totoro_ai/core/extraction/extractors/tiktok.py`)

Handles TikTok URLs.

**Supports check:**
```python
def supports(self, raw_input: str) -> bool:
    # True if "tiktok.com" in netloc
    parsed = urlparse(raw_input)
    return "tiktok.com" in parsed.netloc
```

**Extraction:**
1. Fetch caption via oEmbed API (timeout: 3s)
2. Call InstructorClient with caption text
3. Return ExtractionResult with source=CAPTION

```python
async def extract(self, raw_input: str) -> ExtractionResult | None:
    caption = await self._fetch_tiktok_caption(raw_input)
    extraction = await self._instructor_client.extract(
        response_model=PlaceExtraction,
        messages=[
            {"role": "system", "content": "Extract restaurant details..."},
            {"role": "user", "content": f"Extract from: {caption}"}
        ]
    )
    return ExtractionResult(
        extraction=extraction,
        source=ExtractionSource.CAPTION,
        source_url=raw_input
    )
```

### PlainTextExtractor (`src/totoro_ai/core/extraction/extractors/plain_text.py`)

Handles plain text input.

**Supports check:**
```python
def supports(self, raw_input: str) -> bool:
    # True if not http/https URL
    parsed = urlparse(raw_input)
    return parsed.scheme not in ("http", "https")
```

**Extraction:**
1. Call InstructorClient directly on raw_input
2. Return ExtractionResult with source=PLAIN_TEXT

```python
async def extract(self, raw_input: str) -> ExtractionResult | None:
    extraction = await self._instructor_client.extract(
        response_model=PlaceExtraction,
        messages=[
            {"role": "system", "content": "Extract restaurant details..."},
            {"role": "user", "content": f"Extract from: {raw_input}"}
        ]
    )
    return ExtractionResult(
        extraction=extraction,
        source=ExtractionSource.PLAIN_TEXT,
        source_url=None
    )
```

### GooglePlacesClient (`src/totoro_ai/core/extraction/places_client.py`)

Validates extracted place against Google Places database.

```python
class GooglePlacesClient:
    async def validate_place(
        self, name: str, location: str | None = None
    ) -> PlacesMatchResult:
        # Call Google Places Text Search API
        # Compute name similarity via difflib.SequenceMatcher
        # Return match quality (EXACT, FUZZY, CATEGORY_ONLY, NONE)
```

**Match quality logic:**
- `EXACT`: name similarity ≥ 0.95
- `FUZZY`: name similarity ≥ 0.80
- `CATEGORY_ONLY`: place found but similarity < 0.80
- `NONE`: no match found

### Confidence Scoring (`src/totoro_ai/core/extraction/confidence.py`)

Computes confidence from source + Places match quality.

```python
def compute_confidence(
    source: ExtractionSource,
    match_quality: PlacesMatchQuality,
    corroborated: bool = False,
) -> float:
    # Load weights from config/app.yaml
    # Step 1: base_score from source
    # Step 2: Places modifier (EXACT/FUZZY/CATEGORY_ONLY/NONE)
    # Step 3: multi-source bonus (if corroborated)
    # Step 4: apply max cap (0.95)
    # Return score: 0.0-0.95
```

**Example:**
```
source = CAPTION → base_score = 0.60
match_quality = EXACT → modifier = +0.20
confidence = 0.60 + 0.20 = 0.80 ✓
```

---

## Data Structures

### PlaceExtraction (Request)

Pydantic model from `src/totoro_ai/api/schemas/extract_place.py`.

```python
class PlaceExtraction(BaseModel):
    place_name: str
    address: str
    cuisine: str | None = None
    price_range: str | None = None  # "low", "medium", "high"
```

### ExtractionResult

```python
class ExtractionResult(BaseModel):
    extraction: PlaceExtraction
    source: ExtractionSource  # CAPTION or PLAIN_TEXT
    source_url: str | None = None
```

### PlacesMatchResult

```python
class PlacesMatchResult(BaseModel):
    match_quality: PlacesMatchQuality  # EXACT, FUZZY, CATEGORY_ONLY, NONE
    validated_name: str | None = None
    google_place_id: str | None = None
    lat: float | None = None
    lng: float | None = None
```

### ExtractPlaceResponse (Response)

```python
class ExtractPlaceResponse(BaseModel):
    place_id: str | None  # UUID if saved
    place: PlaceExtraction
    confidence: float  # 0.0-1.0, rounded to 2 decimals
    requires_confirmation: bool
    source_url: str | None  # TikTok URL or null
```

### Place (Database Model)

From `src/totoro_ai/db/models.py`.

```python
class Place(Base):
    id: str  # UUID
    user_id: str
    place_name: str
    address: str
    cuisine: str | None
    price_range: str | None
    lat: float | None
    lng: float | None
    source_url: str | None  # TikTok URL
    google_place_id: str | None  # For deduplication
    confidence: float  # Computed score
    source: str  # CAPTION or PLAIN_TEXT
    created_at: datetime
    updated_at: datetime
```

---

## Execution Flow Example

**Input:** TikTok URL for a ramen restaurant

```python
POST /v1/extract-place
{
    "user_id": "user123",
    "raw_input": "https://www.tiktok.com/@foodie/video/123"
}
```

**Step 1: Validate Input**
- `raw_input` is not empty ✓

**Step 2: Dispatch**
- Dispatcher checks extractors in order
- TikTokExtractor.supports() → True (contains "tiktok.com")
- TikTokExtractor.extract() called

**Step 2a: Fetch Caption**
- httpx call to `https://www.tiktok.com/oembed?url=...`
- Timeout: 3 seconds
- Response: `{ "title": "Fuji Ramen - best tonkotsu in Bangkok!", ... }`
- Caption extracted: `"Fuji Ramen - best tonkotsu in Bangkok!"`

**Step 2b: LLM Extraction**
- InstructorClient.extract() with caption
- Model: GPT-4o-mini (intent_parser from config)
- Returns Pydantic PlaceExtraction:
  ```python
  PlaceExtraction(
      place_name="Fuji Ramen",
      address="123 Sukhumvit Soi 33, Bangkok",
      cuisine="ramen",
      price_range="low"
  )
  ```
- ExtractionResult returned:
  ```python
  ExtractionResult(
      extraction=<PlaceExtraction>,
      source=ExtractionSource.CAPTION,
      source_url="https://www.tiktok.com/@foodie/video/123"
  )
  ```

**Step 3: Validate via Google Places**
- Query: `"Fuji Ramen 123 Sukhumvit Soi 33, Bangkok"`
- API response: First candidate is "Fuji Ramen" at exact address
- Name similarity: difflib ratio = 0.98 (≥ 0.95)
- PlacesMatchResult:
  ```python
  PlacesMatchResult(
      match_quality=PlacesMatchQuality.EXACT,
      validated_name="Fuji Ramen",
      google_place_id="ChIJ...",
      lat=13.7563,
      lng=100.5018
  )
  ```

**Step 4: Compute Confidence**
- Source: CAPTION → base_score = 0.60
- Match quality: EXACT → modifier = +0.20
- Confidence: 0.60 + 0.20 = 0.80
- Final: min(0.80, 0.95) = 0.80

**Step 5: Apply Thresholds**
- confidence = 0.80 ≥ 0.70 ✓ → proceed to save

**Step 6: Deduplication Check**
- Query: `SELECT * FROM places WHERE google_place_id = "ChIJ..." AND user_id = "user123"`
- Result: No match found → proceed to write

**Step 7: Persist**
- Generate UUID: `place_id = "550e8400-e29b-41d4-a716-446655440000"`
- Create Place model:
  ```python
  Place(
      id="550e8400...",
      user_id="user123",
      place_name="Fuji Ramen",
      address="123 Sukhumvit Soi 33, Bangkok",
      cuisine="ramen",
      price_range="low",
      lat=13.7563,
      lng=100.5018,
      source_url="https://www.tiktok.com/@foodie/video/123",
      google_place_id="ChIJ...",
      confidence=0.80,
      source="CAPTION"
  )
  ```
- `db_session.add(place)` + `await db_session.commit()`

**Response:**
```json
{
    "place_id": "550e8400-e29b-41d4-a716-446655440000",
    "place": {
        "place_name": "Fuji Ramen",
        "address": "123 Sukhumvit Soi 33, Bangkok",
        "cuisine": "ramen",
        "price_range": "low"
    },
    "confidence": 0.80,
    "requires_confirmation": false,
    "source_url": "https://www.tiktok.com/@foodie/video/123"
}
```

---

## Error Handling

| Scenario | Exception | HTTP Status | Error Type |
|----------|-----------|-------------|-----------|
| `raw_input` is empty | `ValueError` | 400 | `bad_request` |
| No extractor supports input | `UnsupportedInputError` | 422 | `unsupported_input` |
| Confidence ≤ 0.30 | `ExtractionFailedNoMatchError` | 422 | `extraction_failed_no_match` |
| TikTok oEmbed timeout | `RuntimeError` | 500 | `extraction_error` |
| Google Places API failure | `RuntimeError` | 500 | `extraction_error` |
| Database write failure | `Exception` | 500 | `extraction_error` |

---

## Configuration

Confidence scoring weights are loaded from `config/app.yaml`:

```yaml
extraction:
  confidence_weights:
    base_scores:
      CAPTION: 0.60
      PLAIN_TEXT: 0.60
      SPEECH: 0.50
      OCR: 0.40
    places_modifiers:
      EXACT: 0.20
      FUZZY: 0.15
      CATEGORY_ONLY: 0.10
      NONE_CAP: 0.30
    multi_source_bonus: 0.10
    max_score: 0.95
```

Threshold values are hardcoded in service.py (TODO: move to config):
- Store threshold: 0.70
- Require confirmation threshold: 0.30

---

## Timeouts

- TikTok oEmbed: 3 seconds
- Google Places API: 5 seconds
- Total budget: 10 seconds
- HTTP client default: 30 seconds (NestJS side)

---

## Future Enhancements

- [ ] Move thresholds to config (ADR-028 mentions token-efficient workflow)
- [ ] Add multi-source corroboration (SPEECH + OCR in Phase 3)
- [ ] Support Instagram URLs (Phase 3)
- [ ] Add embedding generation (ADR-040)
- [ ] Implement caching via Redis (ADR-024)
- [ ] Add Langfuse tracing (ADR-025)

---

## Related ADRs

- **ADR-008**: Extraction service orchestration
- **ADR-017**: Extract-place endpoint contract
- **ADR-018**: Confidence scoring for extraction
- **ADR-020**: Provider abstraction (LLM config)
- **ADR-022**: Google Places validation
- **ADR-025**: Langfuse tracing
- **ADR-034**: Two-phase confirmation workflow

See `docs/decisions.md` for full details.
