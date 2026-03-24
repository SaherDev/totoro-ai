# Architecture Rules

## Two-Repo Separation

- **totoro** (product repo): Nx monorepo, Next.js, NestJS, Prisma, PostgreSQL + pgvector. Handles UI, auth (Clerk), CRUD, and product data writes.
- **totoro-ai** (this repo): Pure Python. All AI/ML logic. Writes AI-generated data (places, embeddings, taste_model) to PostgreSQL.
- Communication: HTTP only. The product repo calls this repo's FastAPI endpoints (`/v1/extract-place`, `/v1/consult`).
- This repo never imports from, depends on, or assumes anything about the product repo's internals.

## What This Repo Owns

- Intent parsing (natural language → structured intent)
- Place extraction (free text, URLs, descriptions → structured place data)
- Google Places API calls (place validation and external discovery)
- Embeddings (text → vectors for similarity search)
- Vector similarity search (pgvector queries)
- Writing extracted places, embeddings, and taste model to PostgreSQL
- Ranking (candidates + context → scored recommendations)
- Taste model construction and reading
- Agent orchestration (LangGraph workflows for multi-step reasoning)
- LLM provider abstraction (model switching via config)
- Redis (LLM response caching, session context, agent state — exclusively this repo)
- Evaluations (offline eval harnesses for quality measurement)

## What This Repo Does NOT Own

- UI, frontend, auth, user management, CRUD operations
- Product data writes — users, settings, recommendations belong to NestJS
- Database migrations for product tables — Prisma in the product repo owns users, user_settings, recommendations. Alembic in this repo owns places, embeddings, taste_model.
- Payment, notifications, or any product feature logic

## Database Access

- Write ownership split by domain: FastAPI writes AI data, NestJS writes product data
- FastAPI writes: places, embeddings, taste_model
- FastAPI reads: all tables as needed
- NestJS writes: users, user_settings, recommendations (product data)
- Migration ownership split by domain: Alembic in this repo owns places, embeddings, taste_model. Prisma in product repo owns users, user_settings, recommendations. Never run Prisma migrations against AI tables.
- Database client: SQLAlchemy async + asyncpg
- Redis is owned exclusively by this repo. NestJS does not connect to Redis.

## Provider Abstraction

All LLM and embedding calls go through the provider abstraction layer.

- `config/app.yaml` under `models:` defines logical roles → provider + model + params
- Code references logical roles (e.g., `intent_parser`, `orchestrator`), never model names directly
- Swapping a model means changing `app.yaml` only — no code changes

## Coding Constraints

- **Pydantic for all boundaries**: Function inputs/outputs that cross module boundaries use Pydantic models. No raw dicts.
- **No hardcoded model names**: Always read from config.
- **No `.env` files**: Secrets via environment variables. Non-secret config in `config/*.yaml`.
- **FastAPI routes under `/v1/`**: All endpoints are versioned.
- **LangGraph for agents**: Multi-step AI workflows use LangGraph graphs. Single LLM calls can use LangChain directly.
- **Langfuse on every LLM call**: Attach the Langfuse callback handler to all LLM/embedding invocations for tracing.
