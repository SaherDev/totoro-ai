# Data Model: Consult Pipeline (015)

## New Types — `core/consult/types.py`

### Candidate

Internal model representing a single place under evaluation. Both saved and discovered
places are normalised to this model before ranking.

```
Candidate
  place_id:                str           — unique identifier (from places table or Google)
  place_name:              str
  address:                 str
  cuisine:                 str | None
  price_range:             str | None    — "low" | "mid" | "high" | None
  lat:                     float | None
  lng:                     float | None
  source:                  Literal["saved", "discovered"]
  popularity_score:        float         — 0.0–1.0, normalised from Google rating or 0.5 default
  ambiance:                str | None
  crowd_level:             str | None
  time_of_day:             str | None
  dietary_pref:            str | None
  cuisine_frequency:       str | None
  cuisine_adventurousness: str | None
  distance:                float         — computed distance from search_location in metres, 0.0 if unknown
```

### CandidateMapper (Protocol)

```
Protocol CandidateMapper
  map(source_object: Any) -> Candidate
```

### RecallResultToCandidateMapper

Converts a `RecallResult` to a `Candidate` with `source="saved"`. Distance field is set
to 0.0 at construction time; the ConsultService computes actual distance post-retrieval.

```
RecallResultToCandidateMapper implements CandidateMapper
  map(recall_result: RecallResult) -> Candidate
    place_id   ← recall_result.place_id
    place_name ← recall_result.place_name
    address    ← recall_result.address
    cuisine    ← recall_result.cuisine
    price_range ← recall_result.price_range
    lat        ← recall_result.lat
    lng        ← recall_result.lng
    source     = "saved"
    all taste-signal fields ← None (populated by taste model post-retrieval if available)
    distance   = 0.0
```

### ExternalCandidateMapper

Converts a Google Places Nearby Search result dict to a `Candidate` with `source="discovered"`.

```
ExternalCandidateMapper implements CandidateMapper
  map(google_result: dict) -> Candidate
    place_id   ← google_result["place_id"]
    place_name ← google_result["name"]
    address    ← google_result.get("vicinity", "")
    lat        ← google_result["geometry"]["location"]["lat"]
    lng        ← google_result["geometry"]["location"]["lng"]
    source     = "discovered"
    popularity_score ← normalise(google_result.get("rating", 0.0), max=5.0)
    price_range ← map_price_level(google_result.get("price_level"))
      0 → None, 1 → "low", 2 → "low", 3 → "mid", 4 → "high"
    all taste-signal fields ← None
    distance   = 0.0
```

---

## Updated Types

### ParsedIntent (updated) — `core/intent/intent_parser.py`

Three new fields added:

```
ParsedIntent (updated)
  + validate_candidates:  bool       — true when query signals live validation needed
  + discovery_filters:    dict       — filters to pass to PlacesClient.discover()
                                       e.g. {"opennow": True, "type": "restaurant", "keyword": "sushi"}
  + search_location:      dict | None — resolved lat/lng: {"lat": float, "lng": float}
                                        None only if no location signal and no request lat/lng
```

### RecallResult (updated) — `api/schemas/recall.py`

```
RecallResult (updated)
  + lat:  float | None
  + lng:  float | None
```

### RecallRow (updated) — `db/repositories/recall_repository.py`

```
RecallRow (TypedDict, updated)
  + lat:  float | None
  + lng:  float | None
```

### PlaceResult (updated) — `api/schemas/consult.py`

```
PlaceResult (updated)
  photos:  list[str] = []   (was: list[str] = Field(min_length=1))
```

### ConsultRequest (updated) — `api/schemas/consult.py`

```
ConsultRequest (updated)
  - stream: bool   (field removed)
```

---

## Config Model Updates — `core/config.py`

### RadiusDefaultsConfig (new)

```
RadiusDefaultsConfig
  default:  int   — fallback radius when LLM returns null (metres)
  nearby:   int   — injected into system prompt for "nearby" signals
  walking:  int   — injected into system prompt for "walking distance" signals
```

### ConsultConfig (updated)

```
ConsultConfig (updated)
  + radius_defaults: RadiusDefaultsConfig
```

---

## app.yaml additions

```yaml
consult:
  radius_defaults:
    default: 2000
    nearby: 1000
    walking: 500
```

---

## PlacesClient Protocol extensions — `core/places/places_client.py`

```
PlacesClient (Protocol, extended)
  async validate_place(name, location) -> PlacesMatchResult    (unchanged)
  async discover(search_location: dict, filters: dict) -> list[dict]
    — calls Google Places Nearby Search, returns raw result list
  async validate(candidate: Candidate, filters: dict) -> bool
    — returns True if candidate passes filter constraints (e.g. open now)
```

`GooglePlacesClient` implements all three methods. `validate_place()` is unchanged.

---

## No database schema changes

`places` table already has `lat` and `lng` columns. The SQL queries in
`SQLAlchemyRecallRepository` are updated to select those columns — no Alembic migration
required.
