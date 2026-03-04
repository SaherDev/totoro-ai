# Architecture Rules

## Two-Repo Separation

- **totoro** (product repo): Nx monorepo, Next.js, NestJS, Prisma, PostgreSQL + pgvector. Handles UI, auth (Clerk), CRUD.
- **totoro-ai** (this repo): Pure Python. All AI/ML logic.
- Communication: HTTP only. The product repo calls this repo's FastAPI endpoints.
- This repo never imports from, depends on, or assumes anything about the product repo's internals.

## What This Repo Owns

- Intent parsing (natural language → structured intent)
- Place extraction (free text, URLs, descriptions → structured place data)
- Embeddings (text → vectors for similarity search)
- Ranking (candidates + context → scored recommendations)
- Taste modeling (user preference learning over time)
- Agent orchestration (LangGraph workflows for multi-step reasoning)
- Evaluations (offline eval harnesses for quality measurement)

## What This Repo Does NOT Own

- UI, frontend, auth, user management, CRUD operations
- Database migrations (pgvector instance is owned by product repo on Railway)
- Payment, notifications, or any product feature logic

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
