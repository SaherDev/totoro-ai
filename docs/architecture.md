# System Architecture — Totoro AI Repo

## Overview

This repo (totoro-ai) is the AI engine of Totoro. It owns all AI logic: intent parsing, place extraction, embedding generation, vector retrieval, external discovery, ranking, taste model, and agent orchestration. It runs as a standalone FastAPI service that the product repo calls over HTTP.

```
┌──────────────────────────────────┐
│   totoro (product repo)          │
│   NestJS backend                 │
│   Sends auth-verified requests   │
└───────────────┬──────────────────┘
                │ HTTP (JSON)
                │
                │  POST /v1/extract-place
                │  POST /v1/consult
                │  POST /v1/recall
                ▼
┌──────────────────────────────────────────────────────────┐
│                totoro-ai (this repo)                      │
│                                                           │
│  FastAPI HTTP layer                                       │
│  LangGraph agent orchestration                            │
│  LangChain chains and document loaders                    │
│  Pydantic request/response schemas                        │
│  Provider abstraction (LLM + embedding model switching)   │
└────────┬──────────────┬──────────────┬───────────────────┘
         │              │              │
         │ SQL          │ HTTP         │ TCP
         │ (read-write) │              │
         ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ PostgreSQL   │ │ Google       │ │ Redis        │
│ + pgvector   │ │ Places API   │ │ (cache)      │
│              │ │              │ │              │
│ Writes:      │ │ Validate     │ │ LLM response │
│ - places     │ │ places       │ │ caching      │
│ - embeddings │ │ Discover     │ │ Session      │
│ - taste_model│ │ nearby       │ │ context      │
│              │ │ candidates   │ │ Agent state  │
│ Reads:       │ │              │ │              │
│ - all tables │ │              │ │              │
└──────────────┘ └──────────────┘ └──────────────┘
```

## What This Repo Owns

- Natural language understanding (intent parsing)
- Place extraction from URLs, free text, and screenshots
- Embedding generation
- Writing extracted places and embeddings to PostgreSQL
- Vector similarity search (pgvector queries)
- External place discovery via Google Places API
- Ranking and scoring algorithms (deterministic, tunable)
- Taste model construction and reading
- Agent orchestration via LangGraph
- LLM provider abstraction (model switching via config)
- LLM response caching via Redis
- Evaluation pipeline (retrieval accuracy, agent task completion, token cost, latency)

## What This Repo Does NOT Do

- Serve UI. No HTML, no templates, no static files.
- Manage auth. The product repo validates users before calling.
- Own database migrations for product tables. Alembic in this repo manages migrations for places, embeddings, and taste_model only.
- Write user records, settings, or recommendation history. Those are product data owned by NestJS.

## Data Flow: Extract a Place

extract-place is a deterministic workflow, not an agent. It follows a fixed sequence of steps with one structured LLM extraction call per input type. No tool selection, no reasoning loop, no LangGraph.

```
Raw input (URL + text, text-only, mixed formats)
    │
    ▼
POST /v1/extract-place
    │  Receives: raw_input, user_id
    │
    ├── Parse input to extract URL and supplementary context
    │   Input parser handles: "text before URL text after", "URL only", "text only"
    │   Produces: (url, supplementary_text, input_type)
    │
    ├── Dispatch to appropriate extractor
    │   If URL detected: route to TikTok extractor (for TikTok URLs) or other URL extractors
    │   If no URL: route to PlainText extractor
    │
    ├── Extractor fetches content and runs structured LLM extraction
    │   (TikTok: fetch caption via oEmbed API + merge with supplementary_text)
    │   (PlainText: use raw input text)
    │   Produces: place_name, address, cuisine, price_range
    │
    ├── Validate extracted place via Google Places API
    │   Query for exact match and calculate match quality
    │
    ├── Compute confidence score
    │   Base score from extraction + match quality modifier
    │   Applied to extract-place logic
    │
    ├── Decision: confidence determines action
    │   High confidence → Save to PostgreSQL and return place_id
    │   Mid-range confidence → Return extracted data, require user confirmation
    │   Low confidence → Return error
    │
    └── Return to NestJS: place_id (if saved), extracted data, confidence, decision_reason
```

FastAPI writes only when high-confidence extraction occurs. If mid-range confidence, no write happens until user confirms. NestJS receives the result and decision flag, then decides whether to persist.

Input Parser (src/totoro_ai/core/extraction/input_parser.py) runs before dispatcher routing. It uses regex to detect URLs and extract user-provided context (text before/after the URL). For TikTok inputs, the supplementary text is merged with the video caption before LLM extraction, providing additional context for place identification. Langfuse logs the raw input and parsed components for audit trail and debugging.

## Data Flow: Consult (Recommend a Place)

consult is an agent. It uses LangGraph for multi-step orchestration with tool selection and reasoning. Steps 2 and 3 run as parallel branches because they are independent of each other. Each step passes only the data the next step needs, not the full payload from prior steps. This keeps context tight and reduces token cost.

```
Natural language query (e.g., "cheap dinner nearby")
    │
    ▼
POST /v1/consult
    │  Receives: query, user_id, location
    │
    ▼
LangGraph Agent starts
    │
    ├── Step 1: Parse intent
    │   GPT-4o-mini extracts cuisine, occasion, price, radius, constraints
    │
    ├── Step 2 (parallel branch A): Retrieve saved places
    │   Query pgvector for semantic similarity
    │
    ├── Step 3 (parallel branch B): Discover external candidates
    │   Call Google Places API with location + category filters
    │
    ├── (branches merge)
    │
    ├── Step 4: Validate candidates
    │   Check open hours, live signals
    │
    ├── Step 5: Rank all candidates
    │   Deterministic scoring: taste fit, distance, price, crowd, time context
    │
    └── Step 6: Generate response
        Return 1 primary + 2 alternatives with reasoning to NestJS
        (NestJS stores recommendation history and streams to frontend)
```

The agent runs the full pipeline autonomously. No mid-pipeline callbacks to NestJS.

## Data Flow: Recall (Retrieve Saved Places)

recall is a hybrid search workflow combining vector similarity (pgvector) and full-text search (PostgreSQL FTS) with Reciprocal Rank Fusion (RRF) merging. It retrieves user's saved places matching a natural language query.

```
Natural language query (e.g., "cosy ramen spot")
    │
    ▼
POST /v1/recall
    │  Receives: query, user_id
    │
    ├── Check cold start
    │   count_saved_places(user_id)
    │   If 0: return empty_state=true (no places to search)
    │
    ├── Embed query
    │   Try: query_vector = await embedder.embed(query, input_type="query")
    │   Catch RuntimeError: set query_vector=None (fallback to text-only)
    │
    ├── Hybrid search with RRF merge
    │   If query_vector is not None:
    │     - vector_results: pgvector cosine similarity (<=> operator)
    │       Top limit×candidate_multiplier candidates pre-fetched
    │     - text_results: PostgreSQL FTS (place_name + cuisine)
    │       Matches via plainto_tsquery + ts_rank scoring
    │     - combined: FULL OUTER JOIN with RRF score calculation
    │       RRF formula: 1/(k + rank) per method, summed across both
    │       k=60 (constant, prevents rank=0 dominance)
    │   Else (embedding failed):
    │     - text_only_search: FTS fallback (no vector component)
    │
    ├── Derive match_reason (deterministic, no LLM)
    │   CASE statement in SQL:
    │   - matched_vector=true AND matched_text=true
    │     → "Matched by name, cuisine, and semantic similarity"
    │   - matched_vector=true only
    │     → "Matched by semantic similarity"
    │   - matched_text=true only
    │     → "Matched by name or cuisine"
    │
    └── Return to NestJS
        results: list of RecallResult (place_id, place_name, address, cuisine, etc., match_reason)
        total: count of results
        empty_state: true if user has zero saves, false otherwise
```

**Key properties:**
- Single CTE query: no N+1 queries; all ranking in database
- RRF merging: fairly combines semantic (vector) and keyword (FTS) relevance
- Candidate multiplier: prevents vector results from starving FTS results
- Graceful fallback: text-only path exists; embedding failure does not crash
- Deterministic match_reason: reflects actual search behavior; no guessing

## Intent Classification

Every submission from the input bar is classified into one of three intents before
any pipeline runs. Classification happens in FastAPI as the first step of request
handling — not in NestJS, not in the frontend.

Intent types:

- consult — natural language intent query ("cheap dinner nearby", "good ramen for a date")
- recall — memory fragment referencing a saved place ("that ramen place from TikTok")
- save — URL or place name ("tiktok.com/@foodie/video/123", "Fuji Ramen Bangkok")

Classification rules:

- URL detected via urllib.parse → always save
- Contains memory language ("that", "I saved", "from TikTok/Instagram") → recall
- Everything else → consult
- Default when uncertain → consult

NestJS routes the request to the correct FastAPI endpoint based on intent.
The frontend never sees the classification. The response shape tells the user
what happened.

Empty state rule: the system always returns something. At zero saves, a consult
query returns nearby popular options. A recall with no matches returns the closest
consult result with a note that nothing was found in saves. Never return a
zero-result response.

## API Contract

| Endpoint               | Request                  | Response                                                          |
| ---------------------- | ------------------------ | ----------------------------------------------------------------- |
| POST /v1/extract-place | raw_input, user_id       | place_id, place metadata, confidence score                        |
| POST /v1/consult       | query, user_id, location | 1 primary + 2 alternatives with reasoning                        |
| POST /v1/recall        | query, user_id           | results (list with match_reason), total (count), empty_state (bool) |

All requests come from NestJS after auth verification. This repo never receives requests directly from the frontend.

## Model Assignments

| Logical Role  | Model           | Why                                                                  |
| ------------- | --------------- | -------------------------------------------------------------------- |
| intent_parser | GPT-4o-mini     | Cheap, reliable for structured extraction                            |
| orchestrator  | Claude Sonnet 4 | Strong reasoning for tool calling                                    |
| embedder      | Voyage 4-lite   | 9.25% better retrieval quality than OpenAI; 1024-dimensional vectors |
| evaluator     | GPT-4o-mini     | Cost-effective for batch evals                                       |

Model assignments are config-driven via `config/app.yaml` under the `models:` key. No model names hardcoded in application code.

## Database Access

This repo connects to the same PostgreSQL instance as the product repo.

Writes:

- places (extracted place records)
- embeddings (generated vectors)
- taste_model (learned user patterns)

Reads:

- All tables as needed (places, embeddings, taste_model, users for context)

Does not write:

- users, user_settings, recommendations (product data owned by NestJS)

Schema for AI tables (places, embeddings, taste_model) is managed by Alembic in this repo. If Prisma changes a table this repo reads from (users, recommendations), FastAPI must adapt. Database client: SQLAlchemy async + asyncpg.

## Redis

Redis is owned exclusively by this repo. The product repo does not connect to Redis.

Used for:

- LLM response caching
- Session context
- Intermediate agent state

## Design Principles

- extract-place is a workflow. consult is an agent. These use different implementation patterns. Do not use LangGraph for extract-place.
- The consult agent's tool set should be minimal. Only register tools the agent needs for the current task. Do not preload tools for future capabilities.
- Each LangGraph node passes only the data the next node needs. Do not forward the full Google Places API response, full embedding vectors, or raw validation payloads through downstream steps. Extract the fields needed for ranking and drop the rest.
- Steps 2 (retrieve) and 3 (discover) in the consult pipeline run as parallel LangGraph branches. They are independent and their results merge before validation.

## Design Patterns

These are structural constraints that define how the system is layered.
They describe what lives where and what crosses which boundary.
Behavioral and implementation patterns live in docs/decisions.md.

### Facade — Route Handlers

Route handlers are the HTTP entry point only. Each handler makes
exactly one service call and returns the result. No SQLAlchemy,
no Redis, no pgvector, no Google Places API calls appear inside
src/totoro_ai/api/routes/. All orchestration lives in
src/totoro_ai/core/.

### Protocol — Swappable Dependencies

Any external dependency lives behind a Python Protocol. Concrete
implementations live in src/totoro_ai/providers/ for cross-cutting
dependencies or inside the relevant src/totoro_ai/core/ module for
domain-specific ones. Service layers, agent nodes, and LangGraph
graphs import the Protocol only. Nothing in core/ imports a concrete
provider class directly.

### Repository — Database Access

All SQLAlchemy code lives in four repository classes:
PlaceRepository, EmbeddingRepository, TasteModelRepository, and RecallRepository.
No ORM queries or raw SQL appear outside these classes. Service
and agent layers call repository methods only.

Each repository is defined as a Python Protocol (abstract interface)
with a concrete SQLAlchemy implementation. For example, PlaceRepository
defines two methods:

- `get_by_provider(provider: str, external_id: str) -> Place | None`
  Fetch a place by provider and external ID for deduplication.
- `save(place: Place) -> Place`
  Insert or update a place with explicit error recovery (try/except/rollback).

RecallRepository defines:

- `hybrid_search(user_id: str, query_vector: list[float] | None, query_text: str, limit: int, rrf_k: int, candidate_multiplier: int) -> list[RecallRow]`
  Hybrid search combining pgvector (cosine similarity) and FTS (full-text search) with RRF merging.
  If query_vector is None, falls back to text-only search.
  Returns results with deterministic match_reason (which methods matched).
- `count_saved_places(user_id: str) -> int`
  Count user's saved places for cold-start detection.

The hybrid_search query is a single PostgreSQL CTE (Common Table Expression) with:
- vector_results CTE: pgvector cosine distance ranking (if query_vector provided)
- text_results CTE: FTS ts_rank scoring (keyword matching on place_name + cuisine)
- combined CTE: FULL OUTER JOIN merging both result sets
  RRF score: 1/(k + vector_rank) + 1/(k + text_rank), where k=60
- Final SELECT: top limit results by RRF score, with match_reason derived from which CTEs matched

The Protocol lives in src/totoro_ai/db/repositories/ alongside the
concrete SQLAlchemyRecallRepository implementation. Service layers
depend on the Protocol only, not the concrete class. This allows
testing with mock repositories and swapping implementations without
touching service code. All database writes include try/except blocks
with explicit rollback and structured error logging.

## Key Boundaries

- One shared PostgreSQL instance. Migration ownership split by domain: Prisma owns users, user_settings, recommendations. Alembic in this repo owns places, embeddings, taste_model.
- **Critical constraint**: Embedding vector dimensions must stay in sync across both repos (ADR-040). This repo uses Voyage 4-lite with 1024-dimensional embeddings. The pgvector column in the product repo's Prisma schema must be defined with dimension 1024. If the embedding model changes, both repos must update together to avoid vector dimension mismatches during similarity queries.
- Redis is FastAPI-only.
- Google Places API is called directly by this repo as part of the AI pipeline.
- All LLM and embedding provider calls happen in this repo only.

## Technology Stack

| Layer           | Technology            | Notes                                              |
| --------------- | --------------------- | -------------------------------------------------- |
| Runtime         | Python 3.11           | AI library compatibility                           |
| Package Manager | Poetry                |                                                    |
| HTTP Layer      | FastAPI               | Async, Pydantic-native                             |
| Agent Framework | LangGraph             | Multi-step agent orchestration                     |
| Chains          | LangChain             | Document loaders, retrievers, chains               |
| LLM Providers   | OpenAI, Anthropic     | Via provider abstraction layer                     |
| Embeddings      | Voyage 4-lite         | 1024-dimensional vectors; 32k token context window |
| Monitoring      | Langfuse              | LLM monitoring and evaluation                      |
| Cache           | Redis                 | LLM response caching, session, agent state         |
| Database Client | SQLAlchemy or asyncpg | Read-write connection to PostgreSQL + pgvector     |
| External API    | Google Places API     | Place validation and nearby discovery              |
| Deploy          | Railway               | Hobby $5/mo                                        |
| Local Dev       | Docker Compose        | PostgreSQL + pgvector, Redis, FastAPI              |
