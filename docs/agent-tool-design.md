# Agent & Tool Design — Totoro AI

## Architecture overview

One LangGraph graph. One agent (Claude Sonnet). Three plain async service tools (recall, save, consult). The agent is the only place where LLM reasoning about user context happens. Tools are executors. They take structured input, do their work, return structured output.

Everything goes through `POST /v1/chat`.

---

## Agent state

Loaded once at session start. The agent holds all of this. Tools never fetch it.

```
AgentState
├── messages: list                   ← conversation history
├── taste_profile_summary: str       ← behavior-derived, from taste_model table
│   example: "Prefers casual bars and izakayas over formal dining. [12 signals]
│             Strong proximity bias — consistently chooses places within 1km. [18 signals]
│             Saves frequently from TikTok. [9 signals]
│             Rejects hotel restaurants and omakase. [6 signals]"
│
├── memory_summary: str              ← user-stated facts, from user_memories table
│   example: "Wheelchair user. [95% confidence]
│             Does not eat pork. [95% confidence]
│             Usually dining with partner. [70% confidence]
│             Prefers quiet spots. [80% confidence]"
│
├── user_id: str                     ← injected, hidden from LLM
└── location: {lat, lng} | None      ← from request, optional
```

---

## Agent flow

```
User message arrives via POST /v1/chat
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  LOAD SESSION STATE                                           │
│                                                               │
│  conversation history     ← Redis or message store            │
│  taste_profile_summary    ← taste_model table                 │
│  memory_summary           ← user_memories table               │
│  location                 ← from request payload              │
│  user_id                  ← from request payload              │
└───────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────┐
│  AGENT NODE (Claude Sonnet)                                   │
│                                                               │
│  System prompt includes:                                      │
│  - Food/dining advisor persona                                │
│  - taste_profile_summary (full text, with signal counts)      │
│  - memory_summary (full text, with confidence scores)         │
│  - 3 tool definitions with Pydantic schemas                   │
│                                                               │
│  The agent reads the user message + full context and decides: │
│                                                               │
│  A) Recommendation request → call recall first, then consult  │
│     recall provides saved places, consult merges + ranks      │
│  B) Recall only → user wants to find a saved place            │
│  C) Save → user is sharing a place (URL or text)              │
│  D) Respond directly → general Q&A, chitchat, clarification   │
│                                                               │
│  Intent classification = which tool(s) the agent picks.       │
│  Intent parsing = how the agent fills the tool's fields.      │
│  No separate intent router LLM. No separate intent parser.    │
│  Claude Sonnet does both by constructing the tool call.       │
└───────────────────────────────┬──────────────────────────────┘
                                │
               ┌────────────────┼────────────────┐
               │                │                │
               ▼                ▼                ▼
          [recall]          [save]          [consult]
          plain async       plain async     plain async
          service           service         service
               │                │                │
               └────────────────┼────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────┐
│  AGENT NODE (Claude Sonnet) — post-tool pass                  │
│                                                               │
│  Receives tool results (PlaceObject list + metadata).         │
│  Composes final natural language response using:              │
│  - PlaceObject fields (name, rating, hours, attributes)       │
│  - taste_profile_summary (personal reasoning)                 │
│  - memory_summary (safety checks, hard constraints)           │
│                                                               │
│  May chain another tool:                                      │
│  - recall returned results → pass into consult for ranking    │
│  - consult results all low confidence → refine and re-call    │
│  - user shared a place + asked for similar → save then recall │
│                                                               │
│  Or respond directly if results are sufficient.               │
└───────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
                        SSE stream to client
```

---

## PlaceObject (shared return shape)

Every tool returns PlaceObject instances. Same shape everywhere. Three layers: PostgreSQL (permanent), Redis geo cache (30-day TTL), Redis enrichment cache (4-hour TTL). The agent reads these fields to compose responses.

```
PlaceObject
│
│  --- PostgreSQL (permanent, our data) ---
├── place_id: str
├── place_name: str                  "Fuji Ramen"
├── place_type: str                  "restaurant", "bar", "cafe", "bakery"
├── subcategory: str | None          "izakaya", "ramen", "wine bar"
├── tags: list[str] | None           ["date-night", "outdoor-seating"]
├── attributes: dict | None          {"cuisine": "japanese", "price_hint": "cheap",
│                                      "ambiance": "casual", "dietary": ["vegetarian"],
│                                      "location_context": {
│                                        "neighborhood": "Shibuya",
│                                        "city": "Tokyo",
│                                        "country": "Japan"
│                                      }}
├── source_url: str | None           "https://tiktok.com/..."
├── source: str | None               "tiktok", "instagram", "youtube", "manual"
├── provider_id: str | None          Google's place_id, stored permanently
│
│  --- Redis places:geo:{provider_id} (30-day TTL) ---
├── lat: float | None
├── lng: float | None
├── address: str | None
│
│  --- Redis places:enrichment:{provider_id} (4-hour TTL) ---
├── hours: dict | None               {"monday": "11:00-22:00", ...}
├── rating: float | None
├── phone: str | None
├── photo_url: str | None
├── popularity: float | None         normalized 0-1
│
└── enriched: bool                   true if enrichment cache was hit or fetched
```

**Storage compliance (Google Places API terms):**
- `provider_id` (Google's place_id): PostgreSQL, stored permanently (explicitly allowed)
- `lat`, `lng`, `address`: Redis with 30-day TTL, auto-expires, re-fetched via provider_id on cache miss
- `hours`, `rating`, `phone`, `photo_url`, `popularity`: Redis with 4-hour TTL, short-lived for frequently changing data
- `place_name`, `place_type`, `subcategory`, `tags`, `attributes`: PostgreSQL, our NER extraction from user content, stored permanently
- `location_context` inside attributes: extracted by NER from source content (TikTok captions, user text), not from Google's addressComponents
- No Google content in PostgreSQL. No background refresh job needed. Redis TTL handles expiry.

**When tools populate cache:**
- Save: writes `places:geo:{provider_id}` to Redis after Google Places validation (lat, lng, address with 30-day TTL)
- Consult: writes `places:enrichment:{provider_id}` to Redis after Place Details fetch (hours, rating, etc. with 4-hour TTL)

**When tools read cache:**
- Recall: reads `places:geo:{provider_id}` from Redis to attach lat/lng/address. Cache miss = null fields, no API call.
- Consult: reads `places:enrichment:{provider_id}` first. Cache hit = skip Place Details call. Cache miss = fetch and cache.

---

## Tool: Recall

Retrieves the user's saved places. Two modes: hybrid search (when query is present) and structured filter (when query is null). No LLM calls inside.

### Flow

```
Agent constructs structured input
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  RECALL TOOL                                                  │
│                                                               │
│  Branch: query is not null (search mode)                      │
│  ─────────────────────────────────────                        │
│  1. Build hybrid search query                                 │
│     - query string → embedding via Voyage 4-lite              │
│     - query string → FTS plainto_tsquery                      │
│                                                               │
│  2. Execute single CTE query                                  │
│     - vector_results: pgvector cosine similarity              │
│     - text_results: FTS ts_rank on extracted_name +           │
│       subcategory + address                                   │
│     - combined: FULL OUTER JOIN with RRF scoring              │
│                                                               │
│  3. Apply structured filters as WHERE clauses                 │
│     - place_type, subcategory, source, tags, date range,      │
│       extracted_attributes JSONB paths, distance              │
│                                                               │
│  4. Derive match_reason (deterministic, no LLM)               │
│     - "semantic + keyword" / "semantic" / "keyword"           │
│                                                               │
│  Branch: query is null (filter mode)                          │
│  ────────────────────────────────────                         │
│  1. Execute SELECT with WHERE clauses from filters            │
│     - No embedding, no FTS, no RRF                            │
│     - Pure column/JSONB filtering + ORDER BY                  │
│                                                               │
│  2. match_reason = "filter"                                   │
│                                                               │
│  Both branches return same output shape.                      │
└──────────────────────────────────────────────────────────────┘
```

### Input (agent constructs)

```
{
  query: str | null,
  filters: {
    place_type: str | null,
    subcategory: str | null,
    source: str | null,
    tags_include: list[str] | null,
    extracted_attributes: {
      cuisine: str | null,
      price_hint: str | null,
      ambiance: str | null,
      location_context: {
        neighborhood: str | null,
        city: str | null,
        country: str | null
      }
    } | null,
    max_distance_km: float | null,
    created_after: str | null,
    created_before: str | null
  },
  sort_by: "relevance" | "created_at",  ← default "relevance" when query present,
                                            "created_at" when query is null
  limit: int                             ← default 20
}
```

All fields are optional. The agent includes only what's relevant. Filter shape mirrors the stored object — recall walks the filter and builds matching WHERE clauses against the same JSONB paths.

### How different queries resolve

```
"places I saved from TikTok"
→ recall(query: null, filters: {source: "tiktok"}, sort_by: "created_at")

"all my saved places"
→ recall(query: null, filters: {}, sort_by: "created_at", limit: 50)

"places I saved recently"
→ recall(query: null, filters: {}, sort_by: "created_at", limit: 10)

"that ramen place"
→ recall(query: "ramen", filters: {subcategory: "ramen"}, sort_by: "relevance")

"saved places in Japan"
→ recall(query: "Japan", filters: {extracted_attributes: {location_context: {country: "Japan"}}}, sort_by: "relevance")

"TikTok places in Tokyo"
→ recall(query: null, filters: {source: "tiktok", extracted_attributes: {location_context: {city: "Tokyo"}}}, sort_by: "created_at")

"that ramen place from last week"
→ recall(query: "ramen", filters: {created_after: "2026-04-07"}, sort_by: "relevance")

"date night spots"
→ recall(query: "date night", filters: {tags_include: ["date-night"]}, sort_by: "relevance")

"casual Japanese places"
→ recall(query: null, filters: {extracted_attributes: {cuisine: "japanese", ambiance: "casual"}}, sort_by: "created_at")
```

### Injected (hidden from LLM schema)

```
user_id    ← from AgentState, scopes search to user's saved places
location   ← from AgentState, used for max_distance_km filtering
```

### Output (tool returns)

```
{
  results: [
    {
      place: PlaceObject (enriched: false),
      match_reason: "semantic + keyword",    ← search mode
      relevance_score: 0.87
    },
    {
      place: PlaceObject (enriched: false),
      match_reason: "keyword",
      relevance_score: 0.62
    }
  ],
  total_count: 2
}

// Filter mode (query: null)
{
  results: [
    {
      place: PlaceObject (enriched: false),
      match_reason: "filter",                ← no search, just filtering
      relevance_score: null
    }
  ],
  total_count: 12
}
```

PlaceObject returned with enriched=false. Contains from PostgreSQL: place_id, place_name, place_type, subcategory, tags, attributes, source_url, source, provider_id. Hydrated from Redis geo cache: lat, lng, address (null on cache miss). Does not contain: hours, rating, phone, photo_url, popularity (enrichment cache, only populated by consult).

### LLM calls inside: none

Embedding generation (Voyage 4-lite) is a model call but not an LLM reasoning call. Skipped entirely in filter mode (query: null). No query rewriting, no result summarization, no intent parsing inside this tool.

### Distance filtering

`max_distance_km` requires lat/lng from Redis geo cache. If geo cache miss for a place, that place is excluded from distance filtering but still included in results (distance = null). The agent sees distance = null and handles it in response composition.

---

## Tool: Save

Extracts a place from raw input (URL, text, mixed). Runs the existing extraction cascade. Has internal LLM calls for NER and enrichment — these are pipeline mechanics, not user-context reasoning.

### Flow

```
Agent constructs structured input
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  SAVE TOOL                                                    │
│                                                               │
│  Step 1: Enrich candidates (parallel)                         │
│    - TikTok oEmbed / yt-dlp caption fetch                     │
│    - Regex extraction (place names from text)                 │
│    - LLM NER (GPT-4o-mini) for structured entity extraction  │
│    - Deduplicate by name, apply corroboration bonus           │
│                                                               │
│  Step 2: Validate candidates                                  │
│    - Google Places API validates each candidate               │
│    - Gets provider_id, lat, lng, address from Google          │
│    - Confidence scored per match quality                       │
│                                                               │
│  Step 3: Save                                                 │
│    - Deduplicate by provider_id                               │
│    - If new place:                                            │
│      → write place to PostgreSQL (our extracted data only)    │
│      → write geo to Redis places:geo:{provider_id} (30d TTL) │
│      → generate embedding → write to embeddings table         │
│    - If duplicate: return existing place                      │
│                                                               │
│  Note: the entire pipeline runs as an asyncio background      │
│  task. status: "pending" is always returned immediately.      │
│  If Step 2 finds nothing and a URL is present, Phase 3        │
│  enrichers (subtitle, Whisper audio, vision frames) run       │
│  inline inside ExtractionPipeline before re-validating.       │
│  Final result written to Redis at extraction:{request_id}.    │
│  Caller polls GET /v1/extraction/{request_id} to retrieve.   │
└──────────────────────────────────────────────────────────────┘
```

### Input (agent constructs)

```
{
  raw_input: "https://tiktok.com/@foodie/video/123"
}
```

Minimal input. The agent's job is deciding when to call save, not shaping the extraction. Raw input passes through unchanged.

### Injected (hidden from LLM schema)

```
user_id    ← from AgentState, associates place with user
```

### Output (tool returns)

```
// New place saved
{
  place: PlaceObject (enriched: false),
  confidence: 0.92,
  status: "saved"
}

// Duplicate found
{
  place: PlaceObject (enriched: false),
  confidence: 0.95,
  status: "duplicate"
}

// Background dispatch needed
{
  place: null,
  confidence: null,
  status: "pending"
}

// Extraction failed
{
  place: null,
  confidence: null,
  status: "failed"
}
```

### LLM calls inside: yes (pipeline-internal)

- GPT-4o-mini for NER extraction — output schema matches PlaceObject fields directly:
  extracts extracted_name, place_type, subcategory, tags, and extracted_attributes
  (cuisine, price_hint, ambiance, dietary, location_context) as structured Pydantic output.
  No freeform text. The LLM fills the same shape that Google Places validation
  later enriches. Fields the LLM cannot determine are left null and populated
  by Google Places in Step 2.
- Groq Whisper for audio transcription (background enricher)
- GPT-4o-mini for vision frame extraction (background enricher) — same PlaceObject-aligned
  output schema as NER. Vision extracts extracted_name, subcategory, tags from video frames.

These are specialized extraction capabilities. The agent LLM should not handle them. They run as deterministic pipeline steps inside the tool.

### No context summaries passed

Place extraction is user-context-independent. Knowing that the user prefers izakayas does not change how a TikTok URL gets parsed.

---

## Tool: Consult

Recommends places. Discovers external candidates, merges with saved places the agent already retrieved, deduplicates, ranks deterministically. No internal recall step — the agent calls recall first and passes results in. No intent parsing LLM call — the agent already parsed intent by constructing the tool input.

### Flow

```
Agent calls recall first, then passes results into consult
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  CONSULT TOOL                                                 │
│                                                               │
│  Step 1: Discover external candidates                         │
│    - Calls Google Places API                                  │
│    - Uses query + location + radius + place_type              │
│    - Skipped if no location provided                          │
│    - Google Places populates: photo_url, hours, rating,       │
│      phone, popularity for each discovered place              │
│                                                               │
│  Step 2: Merge saved + discovered                             │
│    - saved_places (from agent's prior recall call)            │
│    - discovered places (from Step 1)                          │
│    - Combined into one candidate pool                         │
│                                                               │
│  Step 3: Deduplicate                                          │
│    - By provider_name + provider_id (exact match)             │
│    - Saved places take priority over discovered duplicates    │
│                                                               │
│  Step 4: Rank all candidates                                  │
│    - Deterministic scoring                                    │
│    - Inputs: taste fit, distance, price match,                │
│      popularity, preference_context alignment                 │
│    - preference_context is a text string the agent composed   │
│      from taste_profile_summary + memory_summary              │
│    - Ranking is code, not LLM                                 │
│                                                               │
│  Step 5: Return ranked list                                   │
└──────────────────────────────────────────────────────────────┘
```

### Input (agent constructs)

```
{
  query: "quiet dinner spot",
  saved_places: [PlaceObject, PlaceObject],    ← from prior recall call
  filters: {
    place_type: "restaurant",
    subcategory: "izakaya",
    tags_include: ["date-night"],
    extracted_attributes: {
      cuisine: "japanese",
      price_hint: "moderate"
    },
    radius_km: 3.0
  },
  location: {lat: 13.7563, lng: 100.5018},
  preference_context: "Prefers izakayas over formal dining. Avoids hotel
    restaurants. Wheelchair user. Does not eat pork."
}
```

`saved_places` comes from the agent's prior recall tool call. The agent calls recall → gets results → passes them into consult as structured input. Consult never touches RecallService. If recall returned nothing, `saved_places` is an empty list and consult works with discovered candidates only.

The agent extracts `preference_context` from `taste_profile_summary` + `memory_summary`. It includes only what's relevant to this specific request.

### Injected (hidden from LLM schema)

```
user_id    ← from AgentState, used for consult log persistence
```

### Output (tool returns)

```
{
  results: [
    {
      place: PlaceObject (enriched: true),
      confidence: 0.94,
      source: "saved"
    },
    {
      place: PlaceObject (enriched: true),
      confidence: 0.81,
      source: "discovered"
    },
    {
      place: PlaceObject (enriched: true),
      confidence: 0.73,
      source: "saved"
    }
  ]
}
```

PlaceObject returned with enriched=true. Contains PostgreSQL fields + Redis geo cache (lat, lng, address) + Redis enrichment cache (hours, rating, phone, photo_url, popularity). For saved places: enrichment fetched via provider_id and cached in `places:enrichment:{provider_id}` with 4-hour TTL. For discovered places: enrichment data comes from the Google Places discovery response and cached in Redis. Subsequent consult calls within 4 hours skip Place Details API calls for the same places.

### LLM calls inside: none

The GPT-4o-mini intent parsing call is eliminated. Claude Sonnet handles intent parsing when it constructs the tool call arguments. Ranking is deterministic code. The tool is a pure data pipeline.

### What preference_context does inside the tool

The ranking step uses preference_context as a text-matching signal. It does not call an LLM to interpret it. The ranking function checks for keyword overlap between preference_context and place attributes/tags. Example: preference_context contains "wheelchair user" → ranking boosts places with "wheelchair-accessible" in tags. This is string matching, not LLM reasoning.

---

## Agent post-tool behavior

```
Tool returns data
    │
    ▼
Agent reads PlaceObject fields + own context
    │
    ├── Composes natural language response
    │   reads: place_name, rating, hours, attributes, photo_url
    │   "Fuji Ramen on Sukhumvit 33 — rated 4.5, open until 22:00"
    │
    ├── Adds personal reasoning from taste_profile_summary
    │   "This matches your pattern of choosing casual izakayas nearby"
    │
    ├── Adds safety checks from memory_summary
    │   "They have step-free access and no pork on the menu"
    │
    ├── Decides if another tool call is needed
    │   recall returned results → pass into consult for ranking + discovery
    │   recall returned 0 → pass empty list into consult, discovery only
    │   consult results all low confidence → refine filters, re-call
    │   user shared a place + asked "anything similar?" → save then recall
    │
    └── Streams final response via SSE

```

---

## Multi-tool sequences

The agent chains tools within a single conversation turn. Recall → consult is the standard recommendation flow.

```
Example 1: Standard recommendation (recall → consult)
─────────────────────────────────────────────────────
User: "find me a good ramen spot nearby"
Agent → recall(query: "ramen restaurant", filters: {place_type: "restaurant", ...})
Recall returns: 2 saved ramen places
Agent → consult(query: "ramen restaurant", saved_places: [2 results], ...)
Consult discovers 4 external + merges 2 saved → ranks all 6
Consult returns: ranked list with confidence scores
Agent composes: "Fuji Ramen is your best bet — you saved it last month and it's 500m away..."

Example 2: No saved places (recall empty → consult discovery only)
─────────────────────────────────────────────────────
User: "where should I eat Thai food tonight?"
Agent → recall(query: "thai restaurant", filters: {...})
Recall returns: total_count: 0
Agent → consult(query: "thai restaurant", saved_places: [], ...)
Consult discovers 5 external candidates → ranks them
Agent composes: "You don't have any saved Thai spots, but here's what's nearby..."

Example 3: Pure recall (no recommendation needed)
─────────────────────────────────────────────────────
User: "show me my saved coffee shops"
Agent → recall(query: "coffee shop", filters: {place_type: "cafe"})
Recall returns: 4 saved cafes
Agent composes the list directly. No consult needed.

Example 4: Save + Recall
─────────────────────────────────────────────
User: "save this https://tiktok.com/... and find me similar spots"
Agent → save(raw_input: "https://tiktok.com/...")
Save returns: PlaceObject (izakaya, japanese, casual)
Agent reads attributes → constructs recall query
Agent → recall(query: "casual japanese izakaya", filters: {...})
Recall returns: 2 matching saved places
Agent composes: "Saved! You also have these similar spots..."

Example 5: Direct response (no tool)
─────────────────────────────────────────────
User: "is tipping expected in Japan?"
Agent has no tool for general Q&A → responds directly
Uses memory_summary for personalization if relevant
```

---

## What changed from previous architecture

| Before | After |
|--------|-------|
| Groq Llama 3.1 8B intent router as first step | Agent picks the tool = intent classification |
| GPT-4o-mini intent parser inside consult | Agent fills Pydantic fields = intent parsing |
| GPT-4o-mini chat_assistant for general Q&A | Agent responds directly, no separate role |
| 4 intent types dispatched to 4 services | 3 tools + direct response from one agent |
| Consult calls RecallService internally | Agent calls recall first, passes saved_places into consult |
| NER extraction outputs freeform fields | NER output schema matches PlaceObject (place_type, subcategory, tags, attributes) |
| cuisine and price_range as top-level columns | Folded into attributes JSONB |
| Each tool returned different shapes | All tools return PlaceObject |
| reasoning_steps array in consult response | Agent streams reasoning via SSE |
| ConsultService persisted consult_logs | Agent or post-tool hook persists logs |
| Context summaries fetched per-service | Agent loads once, passes relevant slices |

---

## Model roles (app.yaml)

| Role | Status | Model | Used by |
|------|--------|-------|---------|
| orchestrator | KEPT — the agent | claude-sonnet-4-6 | Agent LLM (tool calling, reasoning, response composition) |
| embedder | KEPT | voyage-4-lite (1024 dims) | Recall tool (query embedding for pgvector) |
| transcriber | KEPT | whisper-large-v3-turbo (Groq) | Save tool (background audio enricher) |
| vision_frames | KEPT | gpt-4o-mini | Save tool (background vision enricher) |
| evaluator | KEPT | gpt-4o-mini | Eval pipeline (batch evals, offline) |
| intent_router | ELIMINATED | ~~llama-3.1-8b-instant (Groq)~~ | Agent picks which tool to call |
| intent_parser | ELIMINATED | ~~gpt-4o-mini~~ | Agent fills consult tool's Pydantic fields |
| chat_assistant | ELIMINATED | ~~gpt-4o-mini~~ | Agent responds directly for general Q&A |

Three LLM roles absorbed by the orchestrator. Net result: fewer model calls per request, lower latency (no intent router round-trip before the agent starts), and the agent sees full context when parsing intent instead of GPT-4o-mini working without taste/memory summaries.

Tradeoff: Claude Sonnet is more expensive per token than GPT-4o-mini and Groq Llama. For simple Q&A that previously cost ~500 tokens on GPT-4o-mini, you now pay Claude Sonnet rates. This is acceptable because every request already required an orchestrator call — eliminating the router and parser removes two separate LLM round-trips.

A new NER role for the save tool's extraction pipeline stays on GPT-4o-mini. This is pipeline-internal and does not need a separate role name in app.yaml — ExtractionService references the intent_parser role config directly since the model and parameters are identical. If extraction NER needs different settings in the future, add an `extractor_ner` role at that point.

---

## Places storage

```
PostgreSQL (permanent)                Redis (cached, auto-expires)
┌─────────────────────────────┐     ┌──────────────────────────────┐
│ places table                 │     │ places:geo:{provider_id}     │
│                              │     │ TTL: 30 days                 │
│ place_id: str (PK)           │     │ {lat, lng, address}          │
│ user_id: str (indexed)       │     ├──────────────────────────────┤
│ place_name: str              │     │ places:enrichment:{pid}      │
│ place_type: str              │     │ TTL: 4 hours                 │
│ subcategory: str | None      │     │ {hours, rating, phone,       │
│ tags: JSONB | None           │     │  photo_url, popularity}      │
│ attributes: JSONB | None     │     └──────────────────────────────┘
│ source_url: str | None       │
│ source: str | None           │
│ provider_id: str | None      │
│ created_at: datetime         │
│ updated_at: datetime         │
└─────────────────────────────┘

Indexes:
  UNIQUE(provider_id) WHERE provider_id IS NOT NULL
  INDEX(user_id)
  INDEX(user_id, place_type)

FTS index:
  place_name + subcategory
```

No Google content in PostgreSQL. No lat, lng, address, hours, rating, phone, photo_url, popularity columns. All Google-sourced data lives in Redis with TTL-based expiry. Redis already owned exclusively by this repo.

Alembic migration: drop cuisine, price_range, ambiance, lat, lng, address, photo_url, hours, rating, phone, popularity, confidence, validated_at, external_provider columns. Add place_type, subcategory, tags (JSONB), attributes (JSONB). Rename external_id → provider_id, place_name stays as place_name. Data migration moves existing cuisine, price_range values into attributes JSONB. Existing lat/lng/address values seeded into Redis `places:geo:{provider_id}` with 30-day TTL before dropping columns.
