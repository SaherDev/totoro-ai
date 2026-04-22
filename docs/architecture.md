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
                │  POST /v1/chat
                │  GET  /v1/health
                ▼
┌──────────────────────────────────────────────────────────┐
│                totoro-ai (this repo)                      │
│                                                           │
│  FastAPI HTTP layer                                       │
│  Intent classification → pipeline dispatch                │
│  LangChain chains and document loaders                    │
│  Pydantic request/response schemas                        │
│  Provider abstraction (LLM + embedding model switching)   │
└──┬───────────────┬──────────────┬──────────────┬─────────┘
   │               │              │              │
   │ SQL           │ HTTP         │ HTTPS        │ TCP
   │ (read-write)  │              │              │
   ▼               ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ PostgreSQL   │ │ Google       │ │ Groq / OpenAI│ │ Redis        │
│ + pgvector   │ │ Places API   │ │ / Anthropic  │ │ (cache)      │
│              │ │              │ │ / Voyage AI  │ │              │
│ Writes:      │ │ Validate     │ │              │ │ LLM response │
│ - places     │ │ places       │ │ LLM inference│ │ caching      │
│ - embeddings │ │ Discover     │ │ Embeddings   │ │ Extraction   │
│ - taste_model│ │ nearby       │ │ Transcription│ │ status       │
│ - consult_   │ │ Geocode      │ │              │ │ Agent state  │
│   logs       │ │              │ │              │ │              │
│ - user_      │ │              │ │              │ │              │
│   memories   │ │              │ │              │ │              │
│ - interaction│ │              │ │              │ │              │
│   _log       │ │              │ │              │ │              │
│ Reads:       │ │              │ │              │ │              │
│ - all tables │ │              │ │              │ │              │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
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

extract-place is a three-phase deterministic workflow, not an agent. No LangGraph. No tool selection. No reasoning loop. The full pipeline always runs as a background task — the HTTP response returns immediately with `status="pending"` and a `request_id`. The caller polls `GET /v1/extraction/{request_id}` for the final result.

```
Raw input (URL, plain text, or mixed)
    │
    ▼
POST /v1/chat
    │  ChatService classifies intent → "extract-place" → ExtractionService.run()
    │  Returns immediately: { status: "pending", request_id }
    │  asyncio.create_task fires the full pipeline in the background
    │
    └── Background task: ExtractionPipeline.run()
        │
        ├── Phase 1: Enrich candidates
        │   Parallel caption fetch (TikTok oEmbed, yt-dlp), LLM NER
        │   Deduplicate by name; corroborated candidates receive a confidence bonus
        │
        ├── Phase 2: Validate candidates
        │   Google Places API validates each candidate in parallel
        │   Confidence scored per match quality; skip Phase 3 if any pass
        │
        ├── Phase 3: Deep enrichment (only when Phase 2 returns nothing + URL present)
        │   Subtitle check, audio transcription (Whisper), vision frame extraction
        │   Deduplicate → re-validate against Google Places
        │
        └── Persist + write status to Redis at extraction:{request_id}

GET /v1/extraction/{request_id}
    Reads Redis → returns ExtractPlaceResponse (same shape as chat data payload)
    404 while still running or after TTL (1 hour) expires
```

The pipeline runs the full cascade deterministically. No mid-pipeline callbacks to NestJS.

## Data Flow: Consult (Recommend a Place)

consult is a sequential 6-step pipeline implemented in `ConsultService` as a plain Python class (ADR-050: LangGraph parallelization deferred). Each step passes only the data the next step needs, not the full payload from prior steps. ConsultService persists a `consult_logs` record directly after building the response (ADR-053) — NestJS does not store recommendation history.

```
Natural language query (e.g., "cheap dinner nearby")
    │
    ▼
POST /v1/chat
    │  Receives: user_id, message, optional location
    │  ChatService classifies intent → "consult" → dispatches to ConsultService
    │
    ▼
ConsultService.consult()
    │
    ├── Step 1: Parse intent
    │   GPT-4o-mini (intent_parser role) extracts cuisine, occasion, price, radius,
    │   constraints, enriched_query; user memories injected as context
    │
    ├── Step 2: Retrieve saved places
    │   Hybrid search (pgvector + FTS + RRF) via RecallService
    │   Post-filter by price_range and radius if location available
    │
    ├── Step 3: Discover external candidates
    │   Call Google Places API with enriched_query + radius filters
    │   Skipped if no location context
    │
    ├── Step 4: Deduplicate candidates (by external_id, then place_id)
    │
    ├── Step 5: Conditional validation of saved candidates
    │   Validates against live signals only when opennow filter is set
    │
    ├── Step 6: Rank all candidates
    │   Deterministic scoring: taste fit, distance, price, popularity
    │
    └── Step 7: Build response + persist consult log
        Return 1 primary + up to 2 alternatives with reasoning steps
        Persist ConsultLog record (ADR-053); write failures are logged, not raised
```

The pipeline runs fully within FastAPI. No mid-pipeline callbacks to NestJS.

## Data Flow: Recall (Retrieve Saved Places)

recall is a hybrid search workflow combining vector similarity (pgvector) and full-text search (PostgreSQL FTS) with Reciprocal Rank Fusion (RRF) merging. It retrieves user's saved places matching a natural language query.

```
Natural language query (e.g., "cosy ramen spot")
    │
    ▼
POST /v1/chat
    │  ChatService classifies intent → "recall" → dispatches to RecallService
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
    │       min_rrf_score=0.01 (threshold filters low-relevance results)
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
- Min RRF score threshold: filters low-relevance results; configurable via `min_rrf_score` (default 0.01)
- Graceful fallback: text-only path exists; embedding failure does not crash
- Deterministic match_reason: reflects actual search behavior; no guessing

## Agent Orchestration (ADR-062, ADR-065)

All conversational traffic routes through the LangGraph agent (Claude Sonnet 4.6 via the `orchestrator` model role). The agent selects from three tools per turn — recall, save, consult — and returns a `ChatResponse(type="agent")`. The legacy intent-router / intent-parser / chat_assistant dispatch path was deleted in M11 (ADR-065).

## API Contract

| Endpoint                          | Request                               | Response                                              |
| --------------------------------- | ------------------------------------- | ----------------------------------------------------- |
| POST /v1/chat                     | user_id, message, optional location   | type, message, optional data payload (ADR-052)        |
| GET /v1/extraction/{request_id}   | —                                     | ExtractPlaceResponse (results, source_url, request_id); 404 while pending or after TTL |
| GET /v1/health                    | —                                     | status, db connectivity                               |

All requests come from NestJS after auth verification. This repo never receives requests directly from the frontend.

## Model Assignments

| Logical Role  | Model                   | Why                                                                  |
| ------------- | ----------------------- | -------------------------------------------------------------------- |
| orchestrator  | claude-sonnet-4-6       | Strong reasoning for tool calling (LangGraph agent) |
| extractor     | GPT-4o-mini             | NER and subtitle/audio extraction enrichers in the save pipeline |
| embedder      | Voyage 4-lite           | 9.25% better retrieval quality than OpenAI; 1024-dimensional vectors |
| taste_regen   | GPT-4o-mini             | Cost-effective for taste profile summarization |
| vision_frames | GPT-4o-mini             | Frame-level vision extraction for background enricher                |
| transcriber   | whisper-large-v3-turbo (Groq) | Fast multilingual STT; 216x real-time; background audio enricher only (ADR-047) |

Model assignments are config-driven via `config/app.yaml` under the `models:` key. No model names hardcoded in application code.

## Service Configuration

Service-specific parameters are config-driven via `config/app.yaml`:

**Recall Service** (hybrid search tuning):
- `max_results`: Maximum results to return (default 10)
- `rrf_k`: RRF constant for rank weighting (default 60, higher = more weight on top ranks)
- `candidate_multiplier`: Pre-fetch factor (multiplies limit; default 2)
- `min_rrf_score`: Minimum RRF score threshold to filter low-relevance results (default 0.01)

Adjust these values to control result relevance and performance.

**Extraction Service** (cascade tuning):
- `circuit_breaker_threshold`: failures before circuit opens (default 5)
- `circuit_breaker_cooldown`: seconds before half-open probe (default 900)
- `confidence.base_scores`: per-level base confidence — emoji_regex: 0.95, llm_ner: 0.80, subtitle_check: 0.75, whisper_audio: 0.65, vision_frames: 0.55
- `confidence.corroboration_bonus`: bonus when two independent sources find the same name (default 0.10)
- `confidence.max_score`: ceiling — system never claims perfect certainty (default 0.97)
- `vision.max_frames`: maximum frames sent to vision model (default 5)
- `vision.scene_threshold`: ffmpeg scene change threshold (default 0.3)
- `vision.timeout_seconds`: hard timeout for vision enricher (default 10)
- `whisper.timeout_seconds`: hard timeout for audio enricher (default 8)
- `whisper.audio_format`: audio format for in-memory pipe fallback (default opus)
- `whisper.audio_quality`: audio bitrate for in-memory pipe fallback (default 32k)
- `subtitle.output_dir`: temporary directory for VTT files (default /tmp/subtitles)

## Database Access

This repo connects to the same PostgreSQL instance as the product repo.

Writes:

- places (extracted place records)
- embeddings (generated vectors)
- taste_model (learned user patterns)
- consult_logs (AI recommendation history — ADR-053)
- user_memories (personal facts extracted from chat messages)
- interaction_log (append-only behavioral signal log)

Reads:

- All tables as needed (places, embeddings, taste_model, users for context)

Does not write:

- users, user_settings (product data owned by NestJS)

Schema for AI tables (places, embeddings, taste_model, consult_logs, user_memories, interaction_log) is managed by Alembic in this repo. If NestJS changes the users or user_settings table (via TypeORM), FastAPI must adapt. Database client: SQLAlchemy async + asyncpg.

## Redis

Redis is owned exclusively by this repo. The product repo does not connect to Redis.

Used for:

- LLM response caching
- Session context
- Intermediate agent state

## Design Principles

- extract-place is a three-phase workflow (Enrichment → Validation → Deep enrichment), not an agent. No LangGraph. The full pipeline runs as a background asyncio task; the HTTP response returns `pending` immediately. Phase 3 (subtitle/whisper/vision) runs inline inside the pipeline — no domain event dispatch, no separate handler.
- consult is currently a sequential 6-step Python pipeline in `ConsultService` (ADR-050: LangGraph parallelization deferred). If LangGraph is added in the future, Steps 2 (retrieve) and 3 (discover) are the candidates for parallel branches — they are independent and their results merge before validation.
- Each pipeline step passes only the data the next step needs. Do not forward the full Google Places API response, full embedding vectors, or raw validation payloads through downstream steps. Extract the fields needed for ranking and drop the rest.

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

All SQLAlchemy code lives in six repository classes:
PlaceRepository, EmbeddingRepository, TasteModelRepository, RecallRepository,
ConsultLogRepository, and UserMemoryRepository.
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

- `hybrid_search(user_id: str, query_vector: list[float] | None, query_text: str, limit: int, rrf_k: int, candidate_multiplier: int, min_rrf_score: float, max_cosine_distance: float) -> list[RecallRow]`
  Hybrid search combining pgvector (cosine similarity) and FTS (full-text search) with RRF merging.
  If query_vector is None, falls back to text-only search.
  Returns results with deterministic match_reason (which methods matched).
- `count_saved_places(user_id: str) -> int`
  Count user's saved places for cold-start detection.

ConsultLogRepository defines:

- `save(log: ConsultLog) -> None`
  Persist a consult recommendation record (ADR-053). Called by ConsultService after
  building the response; write failures are logged and not raised.

UserMemoryRepository defines:

- `save(user_id: str, memory: str, source: str, confidence: float) -> None`
  Persist an extracted personal fact. Duplicates silently skipped by UNIQUE constraint.
- `load(user_id: str) -> list[str]`
  Load all stored memory strings for a user.

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

### Taste Model

The taste model builds a per-user preference profile from behavioral signals (save, accept, reject, onboarding). Signals aggregate into `signal_counts`; an LLM regen job produces a natural-language `taste_profile_summary` and a structured `chips` array (ADR-058). Chips have a lifecycle — `pending` → `confirmed` / `rejected` via `POST /v1/signal` with `signal_type=chip_confirm` (ADR-061). Confirmed chips are immutable; rejected chips may resurface as pending when the underlying signal count grows. RankingService was deleted — ConsultService returns candidates unranked and an agent (not yet built) will do selection. Full architecture: [docs/taste-model-architecture.md](taste-model-architecture.md).

### Signal Tier (feature 023)

`derive_signal_tier(signal_count, chips, stages, chip_threshold)` — pure function in `core/taste/tier.py` — computes one of `cold`, `warming`, `chip_selection`, `active` from the user's current state. Stages are config-driven (`config/app.yaml → taste_model.chip_selection_stages: dict[str,int]`); adding a new stage (e.g. `round_4: 200`) requires zero code changes because the function iterates `stages.values()` rather than referencing named keys.

The tier is surfaced on `GET /v1/user/context` (plus the full chip array with `status` + `selection_round`). **The product repo gates tier routing** — it reads `/v1/user/context` and decides whether to call `/v1/consult`. At `cold` and `chip_selection` it renders its own UI and never calls consult. At `warming` and `active` it forwards `signal_tier` as a field on `/v1/chat` / `/v1/consult` requests so consult can apply tier-aware behavior (warming 80/20 discovered/saved candidate-count blend; active-tier rejected-chip filter + confirmed-signal reasoning step). `ConsultResponse` is not extended with any envelope — consult is consult.

## Key Boundaries

- One shared PostgreSQL instance. Ownership split by domain: NestJS manages users and user_settings via TypeORM (`synchronize: true`). Alembic in this repo owns places, embeddings, taste_model, consult_logs, user_memories, interaction_log.
- **Critical constraint**: Embedding vector dimensions must stay in sync — but pgvector columns are fully owned by this repo's Alembic migrations. NestJS never touches vector columns. This repo uses Voyage 4-lite with 1024-dimensional embeddings.
- Redis is FastAPI-only.
- Google Places API is called directly by this repo as part of the AI pipeline.
- All LLM, embedding, and transcription provider calls happen in this repo only (OpenAI, Anthropic, Groq, Voyage AI).

## Technology Stack

| Layer           | Technology                     | Notes                                                                 |
| --------------- | ------------------------------ | --------------------------------------------------------------------- |
| Runtime         | Python 3.11                    | AI library compatibility                                              |
| Package Manager | Poetry                         |                                                                       |
| HTTP Layer      | FastAPI 0.115                  | Async, Pydantic-native                                                |
| Agent Framework | LangGraph 0.3                  | Multi-step agent orchestration (deferred for consult — ADR-050)       |
| Chains          | LangChain 0.3                  | Document loaders, retrievers, chains                                  |
| LLM Providers   | OpenAI, Anthropic, Groq        | Via provider abstraction layer; roles mapped in `config/app.yaml`     |
| Intent Router   | llama-3.1-8b-instant (Groq)    | Fast intent classification for all `/v1/chat` traffic                 |
| Extraction / Q&A / Vision / Evals | GPT-4o-mini (OpenAI) | Structured extraction, chat assistant, vision enricher, evals |
| Orchestration   | claude-sonnet-4-6 (Anthropic)  | Strong reasoning for agent/orchestration layer                        |
| Embeddings      | voyage-4-lite (Voyage AI)      | 1024-dimensional vectors; 32k token context window                    |
| Transcription   | whisper-large-v3-turbo (Groq)  | Multilingual STT for background audio enricher (ADR-047)              |
| Structured Output | Instructor 1.0               | LLM output parsing via OpenAI-compatible function calling             |
| Monitoring      | Langfuse 2.0                   | LLM tracing, monitoring, and evaluation                               |
| Cache           | Redis 5.0                      | LLM response caching, extraction status, agent state                  |
| Database Client | SQLAlchemy 2.0 async + asyncpg | Read-write connection to PostgreSQL + pgvector                        |
| Migrations      | Alembic 1.14                   | Manages AI tables: places, embeddings, taste_model, consult_logs, user_memories |
| External API    | Google Places API              | Place validation and nearby discovery                                 |
| Media Extraction | yt-dlp                        | Video metadata and audio extraction for TikTok/YouTube enrichers      |
| Deploy          | Railway                        |                                                                       |
| Local Dev       | Docker Compose                 | PostgreSQL + pgvector, Redis, FastAPI                                 |
