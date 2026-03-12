# CLAUDE.md

**Rule: Keep this file under 150 lines. Move detailed standards to `.claude/rules/` files and reference them here.**

## Project Context

Totoro-ai is the AI engine behind Totoro — an AI-native place decision engine. Users share places over time, the system builds a taste model, and returns one confident recommendation from natural language intent. This repo is pure Python: intent parsing, place extraction, embeddings, ranking, taste modeling, agent orchestration, and evaluations. The product repo (`totoro`) calls this repo over HTTP only. Stack: Python 3.11, Poetry, FastAPI, LangGraph, LangChain, Pydantic, pgvector, Redis, Langfuse. Models: GPT-4o-mini (extraction/evals), Claude Sonnet 4 (orchestration), Voyage 3.5-lite (embeddings later). Deployed on Railway.

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
- **Secrets management** (ADR-026): Per-repo local `config/.local.yaml` (gitignored). Create the file and fill in your secrets — never committed. CI/CD injects secrets as environment variables at deploy time.
- **Provider abstraction**: `config/models.yaml` maps logical roles (intent_parser, orchestrator, embedder) to provider + model + params. Code never hardcodes model names — always reads from config.
- **API versioning**: All FastAPI routes live under `/v1/` prefix to match the product repo convention.
- **Repo boundary**: This repo owns all AI/ML logic. No UI, no auth, no CRUD. The product repo calls this repo via two HTTP endpoints (see `docs/api-contract.md`). Never import from or depend on the product repo.
- **Pydantic everywhere**: Request/response schemas, LLM output parsing, internal data transfer — all Pydantic. No raw dicts crossing function boundaries.
- **LangGraph for orchestration**: Agent workflows use LangGraph graphs, not raw chains.
- **Code quality** — single responsibility, `Depends()` only (no construction inside functions), abstract base class over if/match on provider, repository pattern for all DB access, no duplication (extract to `app/utils/`), new behavior = new class not an edit. Violations must be fixed before presenting code.

See @.claude/rules/architecture.md for full constraints.

## Workflow

See `.claude/workflows.md` for the complete 5-step token-efficient workflow (ADR-028):

1. **Clarify** — If ambiguous (3+ unknowns), ask 5 questions. Record answers in chat.
2. **Plan** — If 3+ files or crosses repo boundary, create `docs/plans/YYYY-MM-DD-<feature>.md` with phases and checklist.
3. **Implement** — Follow plan checklist, write code, commit per `.claude/rules/git.md`.
4. **Verify** — Run verify commands from plan (`pytest`, `ruff check`, `mypy`), all must pass.
5. **Complete** — Mark task done. Update task status only.

**IMPORTANT: Read `docs/decisions.md` FIRST — before planning, before implementing, before any architectural discussion.** Every ADR is a binding constraint. If your approach contradicts a decision, stop and flag it. This is the first thing you do, not a later verification step.

**Constitution Check:** Verify plan aligns with `docs/decisions.md` (see `.claude/constitution.md`).

**Agent Skills Integration:** If agent skills are installed for this repo, they auto-activate based on code domain and workflow stage, not user prompts. Python/FastAPI-focused skills (if any) guide implementation of intent parsing, embeddings, ranking, and agent orchestration. All skill guidance defers to project standards — if a skill recommendation conflicts with `CLAUDE.md`, `architecture.md`, or ADRs, project standards take precedence. Skills are helpers for exploration and implementation, never overrides for project constraints. In particular: provider abstraction patterns, Pydantic schemas, type safety (`mypy --strict`), and LangGraph workflows are binding — no skill bypasses these.

**Model assignments and token costs:** See `.claude/workflows.md` (source of truth).

See @.claude/rules/git.md for branch naming, commit format, and merge flow.

## Notes

- **Task-driven workflow.** Planning and prioritization happen outside this repo (ClickUp). Each task arrives scoped — execute it. No phase gates.
- **Git comment char is `;`** not `#`. Configured in this repo's git config. Commit messages and interactive rebase use `;` for comments.
- **No `.env` files**: Secrets live in `config/.local.yaml`. If a command fails with missing API key, check that `config/.local.yaml` has the correct values.
- **Database write split**: Shared PostgreSQL instance on Railway. This repo writes AI data (places, embeddings, taste_model) and owns their migrations via Alembic. NestJS writes product data (users, settings, recommendations) and owns their migrations via Prisma. Never cross migration tool boundaries.
- **Redis caching**: LLM responses are cached in Redis. When changing prompt templates or model config, consider cache invalidation.
- **Langfuse tracing**: All LLM calls should be traced via Langfuse. Missing traces usually means the Langfuse callback handler wasn't attached.
- **API testing**: Bruno collection at `totoro-config/bruno/`. New endpoints should have a corresponding `.bru` request file added there.
