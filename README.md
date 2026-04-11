# totoro-ai

AI engine for [Totoro](https://github.com/totoro-dev/totoro). Intent classification, place extraction, embeddings, ranking, taste modeling, and agent orchestration. The product repo calls this service over HTTP — see [docs/api-contract.md](docs/api-contract.md) for the full contract.

## Docs

| Doc | What's in it |
|-----|-------------|
| [docs/architecture.md](docs/architecture.md) | System overview, data flows, model assignments, design patterns |
| [docs/api-contract.md](docs/api-contract.md) | HTTP contract between NestJS and this service |
| [docs/decisions.md](docs/decisions.md) | Architecture decision records (ADRs) — read before implementing |
| [docs/taste-model-architecture.md](docs/taste-model-architecture.md) | Taste model dimensions, EMA update formula, ranking integration |

## Setup

```bash
poetry install
cp config/.env.example .env   # fill in secrets
docker compose up -d          # PostgreSQL + Redis
poetry run alembic upgrade head
poetry run uvicorn totoro_ai.api.main:app --reload
```

## Environment Variables

Secrets go in `.env` at the project root (gitignored). Copy `config/.env.example` to get started.

| Variable              | Required | Description |
| --------------------- | -------- | ----------- |
| `DATABASE_URL`        | yes      | PostgreSQL connection URL |
| `REDIS_URL`           | yes      | Redis connection URL |
| `OPENAI_API_KEY`      | yes      | OpenAI — intent parsing, chat assistant, vision, evals |
| `ANTHROPIC_API_KEY`   | yes      | Anthropic — orchestrator role |
| `VOYAGE_API_KEY`      | yes      | Voyage AI — embeddings (voyage-4-lite) |
| `GOOGLE_API_KEY`      | yes      | Google Places API — place validation and discovery |
| `GROQ_API_KEY`        | yes      | Groq — intent router (llama-3.1-8b-instant) and transcription (whisper) |
| `LANGFUSE_PUBLIC_KEY` | yes      | Langfuse — LLM tracing |
| `LANGFUSE_SECRET_KEY` | yes      | Langfuse secret |
| `LANGFUSE_HOST`       | yes      | Langfuse host URL |

Non-secret config (model assignments, extraction weights, service tuning) lives in `config/app.yaml`.

## Commands

```bash
poetry run pytest                          # run tests
poetry run pytest -x                       # stop on first failure
poetry run ruff check src/ tests/          # lint
poetry run mypy src/                       # type check
poetry run alembic revision --autogenerate -m "description"   # new migration
poetry run alembic upgrade head            # apply migrations
```

## Deployment

See [totoro-config/deployment.md](https://github.com/totoro-dev/totoro-config) for Railway deployment, env var setup, and migration runbook.
