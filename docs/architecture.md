# System Architecture

## Two-Repo Structure

```
┌─────────────────────────────────┐      HTTP (JSON)      ┌──────────────────────────────┐
│         totoro (product)        │ ──────────────────────▶│       totoro-ai (this repo)  │
│                                 │                        │                              │
│  Next.js frontend               │  POST /v1/parse-intent │  FastAPI                     │
│  NestJS backend                 │  POST /v1/retrieve     │  LangGraph agents            │
│  Prisma ORM                     │  POST /v1/rank         │  LangChain chains            │
│  Clerk auth                     │  POST /v1/extract-place│  Provider abstraction        │
│  PostgreSQL + pgvector          │                        │  Pydantic schemas            │
│                                 │◀──────────────────────│                              │
│  Railway                        │      JSON responses    │  Railway                     │
└────────────┬────────────────────┘                        └──────────────┬───────────────┘
             │                                                            │
             │  owns migrations                                           │  reads/writes
             ▼                                                            ▼
       ┌───────────┐                                                ┌───────────┐
       │ PostgreSQL │◀──────────────────────────────────────────────│   Redis    │
       │ + pgvector │  both repos query                             │  (cache)   │
       └───────────┘                                                └───────────┘
```

## AI Pipeline Data Flow

```
User query
    │
    ▼
POST /v1/parse-intent
    │  GPT-4o-mini extracts cuisine, occasion, location, constraints
    ▼
POST /v1/retrieve
    │  Query pgvector for saved places (embedding similarity)
    │  Optionally discover new places via external APIs
    ▼
POST /v1/rank
    │  Claude Sonnet 4.6 scores candidates against intent + taste model
    │  Returns 1 primary + 2 alternatives with reasoning
    ▼
JSON response → product repo → user
```

## Place Input Flow

```
Free text (URL, name, or description)
    │
    ▼
POST /v1/extract-place
    │  GPT-4o-mini parses input
    │  URL → fetch + extract place data
    │  Name/description → validate via Google Places API
    ▼
Structured place → stored in PostgreSQL via product repo
```

## Model Assignments

| Logical Role    | Model              | Why                                      |
|-----------------|--------------------|------------------------------------------|
| intent_parser   | GPT-4o-mini        | Cheap, reliable for structured extraction |
| orchestrator    | Claude Sonnet 4.6  | Strong reasoning for tool calling         |
| embedder        | OpenAI (Phase 1-5) | Default start, swap to Voyage Phase 6     |
| evaluator       | GPT-4o-mini        | Cost-effective for batch evals            |

Model assignments are config-driven via `config/models.yaml`. No model names in code.

## Key Boundaries

- **This repo does not serve UI.** No HTML, no templates, no static files.
- **This repo does not manage auth.** The product repo validates users before calling.
- **This repo does not own DB migrations.** pgvector schema is managed by Prisma in the product repo.
- **This repo does own all AI logic.** If it involves an LLM, embedding, or ML model, it lives here.
