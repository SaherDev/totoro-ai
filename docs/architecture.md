# System Architecture — Totoro AI Repo

## Overview

This repo (totoro-ai) is the AI brain of Totoro. It owns all AI logic: intent parsing, place extraction, embedding generation, vector retrieval, external discovery, ranking, and agent orchestration. It runs as a standalone FastAPI service that the product repo calls over HTTP.

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
         │ (read-only)  │              │
         ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ PostgreSQL   │ │ Google       │ │ Redis        │
│ + pgvector   │ │ Places API   │ │ (cache)      │
│              │ │              │ │              │
│ Reads:       │ │ Validate     │ │ LLM response │
│ - places     │ │ places       │ │ caching      │
│ - embeddings │ │ Discover     │ │ Session      │
│ - taste model│ │ nearby       │ │ context      │
│              │ │ candidates   │ │ Agent state  │
│ Writes:      │ │              │ │              │
│ - none       │ │              │ │              │
└──────────────┘ └──────────────┘ └──────────────┘
```

## What This Repo Owns

- Natural language understanding (intent parsing)
- Place extraction from URLs, free text, and screenshots
- Embedding generation
- Vector similarity search (read-only queries against pgvector)
- External place discovery via Google Places API
- Ranking and scoring algorithms (deterministic, tunable)
- Taste model reading (for ranking input)
- Agent orchestration via LangGraph
- LLM provider abstraction (model switching via config)
- LLM response caching via Redis
- Evaluation pipeline (retrieval accuracy, agent task completion, token cost, latency)

## What This Repo Does NOT Do

- Serve UI. No HTML, no templates, no static files.
- Manage auth. The product repo validates users before calling.
- Own database migrations. Prisma in the product repo manages all schema changes.
- Write to PostgreSQL. All database writes go through NestJS in the product repo.

## Data Flow: Extract a Place

```
Raw input (URL, name, or description)
    │
    ▼
POST /v1/extract-place
    │  Receives: raw_input, user_id
    │
    ├── Parse input type (URL, name, description)
    │
    ├── If URL: fetch page content, extract place data
    │   If name/description: search Google Places API
    │
    ├── Validate and enrich via Google Places API
    │
    ├── Generate embedding vector
    │
    └── Return structured place data + embedding vector to NestJS
        (NestJS writes both to PostgreSQL)
```

## Data Flow: Consult (Recommend a Place)

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
    ├── Step 2: Retrieve saved places
    │   Query pgvector directly (read-only) for semantic similarity
    │
    ├── Step 3: Discover external candidates
    │   Call Google Places API with location + category filters
    │
    ├── Step 4: Validate candidates
    │   Check open hours, live signals
    │
    ├── Step 5: Rank all candidates
    │   Deterministic scoring: taste fit, distance, price, crowd, time context
    │
    └── Step 6: Generate response
        Return 1 primary + 2 alternatives with reasoning to NestJS
        (NestJS persists recommendation and streams to frontend)
```

The agent runs the full pipeline autonomously. No mid-pipeline callbacks to NestJS.

## API Contract

| Endpoint               | Request                  | Response                                  |
| ---------------------- | ------------------------ | ----------------------------------------- |
| POST /v1/extract-place | raw_input, user_id       | structured place data + embedding vector  |
| POST /v1/consult       | query, user_id, location | 1 primary + 2 alternatives with reasoning |

All requests come from NestJS after auth verification. This repo never receives requests directly from the frontend.

## Model Assignments

| Logical Role  | Model              | Why                                       |
| ------------- | ------------------ | ----------------------------------------- |
| intent_parser | GPT-4o-mini        | Cheap, reliable for structured extraction |
| orchestrator  | Claude Sonnet 4    | Strong reasoning for tool calling         |
| embedder      | OpenAI (Phase 1-5) | Default start, swap to Voyage in Phase 6  |
| evaluator     | GPT-4o-mini        | Cost-effective for batch evals            |

Model assignments are config-driven via config/models.yaml. No model names hardcoded in application code.

## Database Access

This repo connects to the same PostgreSQL instance as the product repo. The connection is read-only.

Reads from:

- places (place metadata for retrieval context)
- embeddings (vector similarity search via pgvector)
- taste_model_updates (taste patterns used in ranking)

Writes to:

- PostgreSQL: none. All writes go through NestJS.
- Redis: LLM response cache, session context, intermediate agent state.

## Key Boundaries

- One shared PostgreSQL instance. One migration owner (Prisma in product repo). Two connection strings: product repo read-write, this repo read-only.
- Redis is owned exclusively by this repo. The product repo does not connect to Redis.
- Google Places API is called directly by this repo as part of the AI pipeline. The product repo does not call Google Places.
- All LLM and embedding provider calls happen in this repo only.

## Technology Stack

| Layer           | Technology            | Notes                                         |
| --------------- | --------------------- | --------------------------------------------- |
| Runtime         | Python 3.11           | AI library compatibility                      |
| Package Manager | Poetry                |                                               |
| HTTP Layer      | FastAPI               | Async, Pydantic-native                        |
| Agent Framework | LangGraph             | Multi-step agent orchestration                |
| Chains          | LangChain             | Document loaders, retrievers, chains          |
| LLM Providers   | OpenAI, Anthropic     | Via provider abstraction layer                |
| Embeddings      | OpenAI (Phase 1-5)    | Swap to Voyage in Phase 6                     |
| Monitoring      | Langfuse              | LLM monitoring and evaluation                 |
| Cache           | Redis                 | LLM response caching, session, agent state    |
| Database Access | SQLAlchemy or asyncpg | Read-only connection to PostgreSQL + pgvector |
| External API    | Google Places API     | Place validation and nearby discovery         |
| Deploy          | Railway               | Hobby $5/mo                                   |
| Local Dev       | Docker Compose        | PostgreSQL + pgvector, Redis, FastAPI         |
