# Architecture Rules

## Two-Repo Separation

- **totoro** (product repo): Nx monorepo, Next.js, NestJS, Prisma, PostgreSQL + pgvector. Handles UI, auth (Clerk), CRUD, and all database writes.
- **totoro-ai** (this repo): Pure Python. All AI/ML logic. Read-only database access.
- Communication: HTTP only. The product repo calls this repo's FastAPI endpoints (`/v1/extract-place`, `/v1/consult`).
- This repo never imports from, depends on, or assumes anything about the product repo's internals.

## What This Repo Owns

- Intent parsing (natural language → structured intent)
- Place extraction (free text, URLs, descriptions → structured place data)
- Google Places API calls (place validation and external discovery)
- Embeddings (text → vectors for similarity search)
- Vector similarity search (read-only queries against pgvector)
- Ranking (candidates + context → scored recommendations)
- Taste modeling (reading taste patterns for ranking input)
- Agent orchestration (LangGraph workflows for multi-step reasoning)
- LLM provider abstraction (model switching via config)
- Redis (LLM response caching, session context, agent state — exclusively this repo)
- Evaluations (offline eval harnesses for quality measurement)

## What This Repo Does NOT Own

- UI, frontend, auth, user management, CRUD operations
- Database writes — all PostgreSQL writes go through NestJS
- Database migrations — Prisma in the product repo manages all schema changes
- Payment, notifications, or any product feature logic

## Database Access

- This repo has **read-only** access to PostgreSQL + pgvector
- Reads: places, embeddings, taste_model_updates
- Writes: none. All writes (place records, embeddings, taste updates) go through NestJS
- Redis is owned exclusively by this repo. NestJS does not connect to Redis.

## Provider Abstraction

All LLM and embedding calls go through the provider abstraction layer.

- `config/models.yaml` defines logical roles → provider + model + params
- Code references logical roles (e.g., `intent_parser`, `orchestrator`), never model names directly
- Swapping a model means changing YAML config, not code

## Coding Constraints

- **Pydantic for all boundaries**: Function inputs/outputs that cross module boundaries use Pydantic models. No raw dicts.
- **No hardcoded model names**: Always read from config.
- **No `.env` files**: Secrets via environment variables. Non-secret config in `config/*.yaml`.
- **FastAPI routes under `/v1/`**: All endpoints are versioned.
- **LangGraph for agents**: Multi-step AI workflows use LangGraph graphs. Single LLM calls can use LangChain directly.
- **Langfuse on every LLM call**: Attach the Langfuse callback handler to all LLM/embedding invocations for tracing.
