# CLAUDE.md

**Rule: Keep this file under 150 lines. Move detailed standards to `.claude/rules/` files and reference them here.**

## Project Context

Totoro-ai is the AI engine behind Totoro — an AI-native place decision engine. Users share places over time, the system builds a taste model, and returns one confident recommendation from natural language intent. This repo is pure Python: intent parsing, place extraction, embeddings, ranking, taste modeling, agent orchestration, and evaluations. The product repo (`totoro`) calls this repo over HTTP only. Stack: Python 3.11, Poetry, FastAPI, LangGraph, LangChain, Pydantic, Instructor, pgvector, Redis, Langfuse. Models: llama-3.1-8b-instant/Groq (intent routing), GPT-4o-mini/OpenAI (intent parsing, chat assistant, vision, evals), claude-sonnet-4-6/Anthropic (orchestration), voyage-4-lite/Voyage AI (embeddings), whisper-large-v3-turbo/Groq (transcription). SDKs: OpenAI SDK, Anthropic SDK, Groq SDK, Voyage AI SDK. Deployed on Railway.

## Key Directories

- `src/totoro_ai/` — main package (src layout)
  - `api/` — FastAPI routes and request/response schemas
  - `core/` — domain modules: intent/, extraction/, memory/, ranking/, taste/, agent/ (intent parsing, place extraction, memory and retrieval, ranking, taste modeling, agent orchestration)
  - `providers/` — LLM/embedding provider abstraction (config-driven via YAML)
  - `eval/` — evaluation harnesses and datasets
- `tests/` — pytest tests mirroring src structure
- `config/` — YAML configuration (`app.yaml` for all non-secret settings: app metadata, model roles, extraction config)
- `scripts/` — utility scripts
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
docker compose up -d                  # start services (PostgreSQL, Redis) in detached mode
docker compose up -d --build          # start services and rebuild images
docker compose down                   # stop services
docker compose down -v                # stop services and remove volumes
```

## Standards

- **Naming**: snake_case everywhere. Pydantic models are PascalCase. Files match module name.
- **Types**: All function signatures typed. Pydantic models for all LLM input/output schemas. `mypy --strict` is the target.
- **Secrets management** (ADR-051): `.env` in the project root (gitignored symlink → `totoro-config/secrets/ai.env.local`). Copy `config/.env.example`, fill in your secrets — never committed. CI/CD injects secrets as environment variables at deploy time.
- **Provider abstraction**: `config/app.yaml` under `models:` maps logical roles (intent_router, intent_parser, chat_assistant, orchestrator, embedder, etc.) to provider + model + params. Code never hardcodes model names — always reads from config.
- **API versioning**: All FastAPI routes live under `/v1/` prefix to match the product repo convention.
- **Repo boundary**: This repo owns all AI/ML logic. No UI, no auth, no CRUD. The product repo calls this repo via `POST /v1/chat` (unified conversational entry — ADR-052) and `GET /v1/health` (see `docs/api-contract.md`). Never import from or depend on the product repo.
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

- **Task-driven workflow.** Each task arrives scoped — execute it. No phase gates.
- **Git comment char is `;`** not `#`. Configured in this repo's git config. Commit messages and interactive rebase use `;` for comments.
- **Secrets in `.env`**: Root `.env` (gitignored symlink). Non-secret config (app metadata, models, extraction weights) lives in `config/app.yaml` (committed). If a command fails with missing API key, check `totoro-config/secrets/ai.env.local`.
- **Database write split**: Shared PostgreSQL instance on Railway. This repo writes AI data (places, embeddings, taste_model, recommendations, user_memories, interaction_log) and owns their migrations via Alembic. NestJS writes product data (users, user_settings) via TypeORM with `synchronize: true`. Never cross ownership boundaries.
- **Redis caching**: LLM responses are cached in Redis. When changing prompt templates or model config, consider cache invalidation.
- **Langfuse tracing**: All LLM calls should be traced via Langfuse. Missing traces usually means the Langfuse callback handler wasn't attached.
- **API testing**: Bruno collection at `totoro-config/bruno/`. New endpoints should have a corresponding `.bru` request file added there.

## Recent Changes
- 028-agent-tools-wiring: `ConsultService` signature now takes pre-parsed args (`saved_places`, `ConsultFilters`, `preference_context`) plus optional `emit` callback; `IntentParser`/`UserMemoryService`/main-path taste-profile load removed (active-tier chip-filter taste read retained, ADR-061). `EmitFn` in `core/emit.py` is a `typing.Protocol` (not a `Callable` alias — third arg `duration_ms: float | None = None` has a default); services (recall, consult, extraction) emit primitive `(step, summary[, duration_ms])` tuples at each pipeline boundary; wrappers add agent-layer fields (`source`/`tool_name`/`visibility`/`timestamp`/`duration_ms`) via shared `core/agent/tools/_emit.py` helpers (`build_emit_closure` + `append_summary`) with `langgraph.config.get_stream_writer()` fan-out. `ReasoningStep` (027) gains `duration_ms: float | None = None` — populated by service when measured, by closure's timestamp delta otherwise; `tool.summary` carries total tool-invocation elapsed. **`ConsultResponse.reasoning_steps` field deleted** — steps delivered live via `emit` instead; `_persist_recommendation` no longer stores them. Shared `PlaceFilters` base in `core/places/filters.py` mirrors `PlaceObject` (ADR-056); `RecallFilters` / `ConsultFilters` extend it — `RecallFilters` migrates from dataclass to Pydantic. Three `@tool`-decorated wrappers under `core/agent/tools/` (`recall_tool`, `save_tool`, `consult_tool`) — `Annotated[..., InjectedState]` for runtime state access on LangGraph 0.3 (not `ToolRuntime`); `user_id`/`location`/`saved_places` hidden from LLM-visible `args_schema`; `saved_places` flows tool→tool via `state["last_recall_results"]`. `config/prompts/agent.txt` updated to instruct the orchestrator to emit one tool call per response — primary mitigation for the last-write-wins race on `AgentState.reasoning_steps` (the field has no reducer by design). `ChatService.run` forks on `config.agent.enabled` (per-request read); flag-off path preserved; flag-on `_run_agent` loads taste/memory summaries, builds turn payload, invokes compiled graph, filters `reasoning_steps` to `visibility="user"`, returns `ChatResponse(type="agent", ...)` (new literal on a tightened `ChatResponse.type` Literal). Compiled graph built once per process via FastAPI `lifespan` → `app.state.agent_graph`; `get_agent_graph` FastAPI dependency reads it. Per-tool timeouts NOT enforced in this feature (deferred to M9). Flag defaults to off — no user-facing behavior change on deploy.
- 027-agent-foundation: ExtractPlaceResponse two-level status + `raw_input` rename (ADR-063); Redis prefix `extraction:v2`; `ExtractionService.run()` awaits inline, route-layer `create_task` preserves HTTP pending behavior; `agent:` config block (`enabled: false`, `max_steps`, `max_errors`, per-tool timeouts) + `config/prompts/agent.txt` (eager slot validation at boot); `core/agent/` skeleton (state, reasoning, invocation, graph, checkpointer) with Postgres `AsyncPostgresSaver`; Alembic excludes checkpointer tables via `db/alembic_exclusion.py`. `ReasoningStep` re-exported on `api/schemas/consult.py` with `source`/`tool_name`/`visibility`. `RecallFilters` refactored to mirror `PlaceObject` (nested `attributes: PlaceAttributes`). No user-visible behavior change aside from the new extraction envelope.
- 023-onboarding-signal-tier: Signal tier (cold/warming/chip_selection/active) derived from config-driven `chip_selection_stages` (ADR-061). `GET /v1/user/context` returns `signal_tier` + chips with `status`/`selection_round`. Product repo gates tier routing — it reads `/v1/user/context` and forwards `signal_tier` on `/v1/chat` + `/v1/consult` requests; `ConsultResponse` is NOT extended with an envelope. New `chip_confirm` variant on `POST /v1/signal` writes a CHIP_CONFIRM interaction row with metadata, merges chip statuses (confirmed immutable; rejected may resurface when signal grows), and dispatches `ChipConfirmed` which forces an immediate taste-profile rewrite. Warming tier applies a config-driven 80/20 discovered/saved candidate-count blend.


## Active Technologies
- `PlaceFilters` / `RecallFilters` / `ConsultFilters` family in `core/places/filters.py` + `core/recall/types.py` (Pydantic extensions of a shared base mirroring `PlaceObject` per ADR-056) (028-agent-tools-wiring)
- `EmitFn` primitive callback pattern in `core/emit.py`; recall/consult/extraction services gain optional `emit` parameter; `ConsultResponse.reasoning_steps` removed (028-agent-tools-wiring)
- `core/agent/tools/` module (LangGraph 0.3 tools via `@tool` + `Annotated[..., InjectedState]`; `saved_places` threaded tool→tool via `state["last_recall_results"]`; shared `_emit.py` helpers fan out to `langgraph.config.get_stream_writer()`); compiled graph warmed eagerly in `api/main.py` lifespan; `agent.enabled` flag read per-request in `ChatService.run` (028-agent-tools-wiring)

