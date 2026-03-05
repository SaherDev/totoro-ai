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
- Own database migrations. Prisma in the product repo manages all schema changes.
- Write user records, settings, or recommendation history. Those are product data owned by NestJS.

## Data Flow: Extract a Place

extract-place is a deterministic workflow, not an agent. It follows a fixed sequence of steps with one LLM call for parsing. No tool selection, no reasoning loop, no LangGraph.

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
    ├── Write place record + embedding to PostgreSQL
    │
    └── Return place_id, extracted metadata, and confidence score to NestJS
```

FastAPI writes what it generates. NestJS receives a confirmation, not raw data to persist.

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

## API Contract

| Endpoint               | Request                  | Response                                   |
| ---------------------- | ------------------------ | ------------------------------------------ |
| POST /v1/extract-place | raw_input, user_id       | place_id, place metadata, confidence score |
| POST /v1/consult       | query, user_id, location | 1 primary + 2 alternatives with reasoning  |

All requests come from NestJS after auth verification. This repo never receives requests directly from the frontend.

## Model Assignments

| Logical Role  | Model              | Why                                       |
| ------------- | ------------------ | ----------------------------------------- |
| intent_parser | GPT-4o-mini        | Cheap, reliable for structured extraction |
| orchestrator  | Claude Sonnet 4    | Strong reasoning for tool calling         |
| embedder      | OpenAI text-embedding-3-small | Default; swappable to Voyage via config |
| evaluator     | GPT-4o-mini        | Cost-effective for batch evals            |

Model assignments are config-driven via config/models.yaml. No model names hardcoded in application code.

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

Schema is defined by Prisma in the product repo. If a migration changes a table this repo writes to, FastAPI must adapt. Database client: SQLAlchemy or asyncpg.

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

## Key Boundaries

- One shared PostgreSQL instance. One schema owner (Prisma in product repo). Write ownership split by domain: FastAPI writes AI data, NestJS writes product data.
- Redis is FastAPI-only.
- Google Places API is called directly by this repo as part of the AI pipeline.
- All LLM and embedding provider calls happen in this repo only.

## Technology Stack

| Layer           | Technology            | Notes                                          |
| --------------- | --------------------- | ---------------------------------------------- |
| Runtime         | Python 3.11           | AI library compatibility                       |
| Package Manager | Poetry                |                                                |
| HTTP Layer      | FastAPI               | Async, Pydantic-native                         |
| Agent Framework | LangGraph             | Multi-step agent orchestration                 |
| Chains          | LangChain             | Document loaders, retrievers, chains           |
| LLM Providers   | OpenAI, Anthropic     | Via provider abstraction layer                 |
| Embeddings      | OpenAI text-embedding-3-small | Swappable to Voyage via config          |
| Monitoring      | Langfuse              | LLM monitoring and evaluation                  |
| Cache           | Redis                 | LLM response caching, session, agent state     |
| Database Client | SQLAlchemy or asyncpg | Read-write connection to PostgreSQL + pgvector |
| External API    | Google Places API     | Place validation and nearby discovery          |
| Deploy          | Railway               | Hobby $5/mo                                    |
| Local Dev       | Docker Compose        | PostgreSQL + pgvector, Redis, FastAPI          |
