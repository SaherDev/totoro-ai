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

Before implementing, ask clarifying questions if the task has ambiguity. Do not assume. Keep questions to 3 or fewer. If the task is fully scoped with no ambiguity, skip questions and start executing.

Before touching code, answer six questions:

**Context checks:**
1. **Which phase?** — Only build what the current phase requires. Do not build ahead.
2. **Crosses repo boundary?** — If it touches UI/auth/CRUD, it belongs in `totoro`. If it touches AI/ML logic, it belongs here.
3. **Existing pattern?** — Find a similar file or module and follow its conventions.

**File-level checks:**
4. **What file(s) will change?** — Read them first.
5. **What could break?** — Identify side effects across modules.
6. **Is this the simplest change?** — Do not over-engineer.

Then follow this cycle:
1. **Plan** — If the task touches 3+ files or involves scaffolding, write a plan in chat under 20 lines. For tasks touching 1–2 files, skip the plan and go straight to implementation.
2. **Implement** — Make the smallest change that works. One concern per commit.
3. **Verify** — Run `pytest`, `ruff check`, `mypy`. All must pass before moving on.
4. **Completion report** — 5 lines or less. What changed, what was tested, any deviations from the plan.

**Token efficiency rules:**
- Plans go in chat, not in separate files.
- Do not repeat file contents back after creating or editing them.
- Do not explain code you just wrote unless asked.
- Do not list what you are about to do and then do it. Pick one: explain or execute.
- Keep commit messages to one line. Add a body only if the change is non-obvious.

See @.claude/rules/git.md for branch naming, commit format, and merge flow.

## Notes

- **Current phase: 0.5.** Only Phase 0.5 and Phase 1 content applies. Do not build ahead.
- **Git comment char is `;`** not `#`. Configured in this repo's git config. Commit messages and interactive rebase use `;` for comments.
- **No `.env` files**: Secrets are exported in shell. If a command fails with missing API key, check that `scripts/env-setup.sh` values are exported.
- **pgvector is shared**: The PostgreSQL + pgvector instance is owned by the product repo on Railway. This repo connects to it but does not manage migrations.
- **Redis caching**: LLM responses are cached in Redis. When changing prompt templates or model config, consider cache invalidation.
- **Langfuse tracing**: All LLM calls should be traced via Langfuse. Missing traces usually means the Langfuse callback handler wasn't attached.
