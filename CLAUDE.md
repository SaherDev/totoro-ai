# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Context

Totoro-ai is the AI engine behind Totoro — an AI-native place decision engine. Users share places over time, the system builds a taste model, and returns one confident recommendation from natural language intent. This repo is pure Python: intent parsing, place extraction, embeddings, ranking, taste modeling, agent orchestration, and evaluations. The product repo (`totoro`) calls this repo over HTTP only. Stack: Python 3.11, Poetry, FastAPI, LangGraph, LangChain, Pydantic, pgvector, Redis, Langfuse. Models: GPT-4o-mini (extraction/evals), Claude Sonnet 4.6 (orchestration), Voyage 3.5-lite (embeddings later). Deployed on Railway.

## Key Directories

- `src/totoro_ai/` — main package (src layout)
  - `api/` — FastAPI routes and request/response schemas
  - `core/` — domain modules: intent/, extraction/, memory/, ranking/, taste/, agent/ (intent parsing, place extraction, memory and retrieval, ranking, taste modeling, agent orchestration)
  - `providers/` — LLM/embedding provider abstraction (config-driven via YAML)
  - `eval/` — evaluation harnesses and datasets
- `tests/` — pytest tests mirroring src structure
- `config/` — YAML configuration (models.yaml for provider switching, non-secret settings)
- `scripts/` — utility scripts (env-setup.sh template for secrets)
- `docs/` — operational docs: architecture, API contract, decisions log

See @.claude/rules/architecture.md for repo boundaries and coding constraints.

## Common Commands

```bash
poetry install                        # install dependencies
poetry run uvicorn totoro_ai.api.main:app --reload      # dev server
poetry run pytest                     # run all tests
poetry run pytest tests/path/test_file.py::test_name    # single test
poetry run pytest -x                  # stop on first failure
poetry run ruff check src/ tests/     # lint
poetry run ruff format src/ tests/    # format
poetry run mypy src/                  # type check
```

## Standards

- **Naming**: snake_case everywhere. Pydantic models are PascalCase. Files match module name.
- **Types**: All function signatures typed. Pydantic models for all LLM input/output schemas. `mypy --strict` is the target.
- **Config**: Non-secret config in `config/*.yaml`. Secrets via environment variables only (never `.env` files). `scripts/env-setup.sh` has the template.
- **Provider abstraction**: `config/models.yaml` maps logical roles (intent_parser, orchestrator, embedder) to provider + model + params. Code never hardcodes model names — always reads from config.
- **API versioning**: All FastAPI routes live under `/v1/` prefix to match the product repo convention.
- **Repo boundary**: This repo owns all AI/ML logic. No UI, no auth, no CRUD. The product repo calls this repo via four HTTP endpoints (see `docs/api-contract.md`). Never import from or depend on the product repo.
- **Pydantic everywhere**: Request/response schemas, LLM output parsing, internal data transfer — all Pydantic. No raw dicts crossing function boundaries.
- **LangGraph for orchestration**: Agent workflows use LangGraph graphs, not raw chains.

See @.claude/rules/architecture.md for full constraints.

## Workflow

Before touching code, answer three questions:
1. Which phase does this belong to?
2. Does this cross the repo boundary?
3. Is there an existing pattern to follow?

Then: **plan → implement → verify**.

- **Plan**: Read relevant docs/ and existing code. State what you will change and why.
- **Implement**: One logical change per commit. Follow existing patterns.
- **Verify**: Run `pytest`, `ruff check`, `mypy`. All must pass before considering done.
- **Completion report**: Summarize what changed, what was tested, flag any deviations from the plan.

See @.claude/rules/git.md for branch naming, commit format, and merge flow.

## Notes

- **Current phase: 0.5.** Only Phase 0.5 and Phase 1 content applies. Do not build ahead.
- **Git comment char is `;`** not `#`. Configured in this repo's git config. Commit messages and interactive rebase use `;` for comments.
- **No `.env` files**: Secrets are exported in shell. If a command fails with missing API key, check that `scripts/env-setup.sh` values are exported.
- **pgvector is shared**: The PostgreSQL + pgvector instance is owned by the product repo on Railway. This repo connects to it but does not manage migrations.
- **Redis caching**: LLM responses are cached in Redis. When changing prompt templates or model config, consider cache invalidation.
- **Langfuse tracing**: All LLM calls should be traced via Langfuse. Missing traces usually means the Langfuse callback handler wasn't attached.
