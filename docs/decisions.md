# Architecture Decisions

Log of architectural decisions. Add new entries at the top.

Format:
```
## ADR-NNN: Title

**Date:** YYYY-MM-DD

**Status:** accepted | superseded | deprecated

**Context:** Why this decision was needed.

**Decision:** What we decided.

**Consequences:** What follows from this decision.
```

---

## ADR-025: Langfuse callback handler on all LLM invocations

**Date:** 2026-03-07

**Status:** accepted

**Context:** Without tracing, there is no visibility into which LLM calls are slow, expensive, or producing bad outputs. Langfuse is already in the stack for monitoring and evaluation.

**Decision:** Every LLM and embedding call attaches a Langfuse callback handler at invocation time. Implementation pending in `src/totoro_ai/providers/tracing.py`, which will expose a `get_langfuse_handler()` factory. All provider wrappers call it when building `callbacks=` lists. No call goes untraced.

**Consequences:** Full per-call observability (latency, tokens, cost, input/output). Missing traces in Langfuse indicate a provider call that bypassed the abstraction layer. Implementation pending.

---

## ADR-024: Redis caching layer for LLM responses

**Date:** 2026-03-07

**Status:** accepted

**Context:** Repeated identical LLM calls (e.g. same intent string, same place description) waste tokens and add latency. Redis is already in the stack owned exclusively by this repo.

**Decision:** LLM responses are cached in Redis keyed by a hash of (role, prompt, model, temperature). Cache is applied inside the provider abstraction layer so callers remain unaware. When prompt templates or model config change, cache must be explicitly invalidated. Implementation pending in `src/totoro_ai/providers/cache.py`.

**Consequences:** Reduces token cost and latency for repeated queries. Requires cache invalidation discipline when prompts or models change. Redis client injected via FastAPI dependency. Implementation pending.

---

## ADR-023: HTTP error mapping from FastAPI to NestJS

**Date:** 2026-03-07

**Status:** accepted

**Context:** NestJS acts on HTTP status codes from this service. Without a consistent error contract, the product repo cannot distinguish bad input from internal failures, leading to incorrect user-facing messages.

**Decision:** FastAPI registers exception handlers that map internal error types to the HTTP codes defined in the API contract: 400 for malformed input, 422 for unparseable intent or no results, 500 for unexpected failures. All error responses return a JSON body with `detail` string. Implementation pending in `src/totoro_ai/api/errors.py`, registered in `api/main.py`.

**Consequences:** NestJS can reliably act on status codes. 422 triggers a "couldn't understand" message. 500 triggers a 503 with retry suggestion. Implementation pending.

---

## ADR-022: Google Places API client abstraction

**Date:** 2026-03-07

**Status:** accepted

**Context:** Google Places API is called in two contexts: validating extracted places (extract-place workflow) and discovering nearby candidates (consult agent). Without abstraction, both callers would duplicate HTTP setup, auth, and error handling.

**Decision:** A dedicated client class wraps all Google Places API calls. Implementation pending in `src/totoro_ai/core/extraction/places_client.py`. Exposes two methods: `validate_place(name, location)` and `discover_nearby(location, category, radius)`. API key loaded from environment variable, never from config files.

**Consequences:** Single place for Google Places error handling and response normalization. Both extract-place and consult use the same client. Implementation pending.

---

## ADR-021: LangGraph graph for consult agent orchestration

**Date:** 2026-03-07

**Status:** accepted

**Context:** The consult pipeline has six steps with a parallel branch (retrieve + discover) and conditional logic. A sequential async function cannot express the parallel branch or the per-node data contracts cleanly.

**Decision:** consult is implemented as a LangGraph `StateGraph`. Each pipeline step (intent parsing, retrieval, discovery, validation, ranking, response generation) is a named node. Steps 2 and 3 run as parallel branches per ADR-009. Each node defines its input/output fields explicitly per ADR-010. Implementation pending in `src/totoro_ai/core/agent/graph.py`. Graph is compiled once at startup and invoked per request.

**Consequences:** Pipeline is inspectable, testable node-by-node, and extensible without touching other nodes. Graph compilation at startup catches schema errors early. Implementation pending.

---

## ADR-020: Provider abstraction layer — config-driven LLM and embedding instantiation

**Date:** 2026-03-07

**Status:** accepted

**Context:** Application code must never hardcode model names or provider-specific imports. `config/models.yaml` already defines logical roles but nothing reads it to produce LLM objects yet.

**Decision:** A provider abstraction module reads `config/models.yaml` and returns initialized LangChain-compatible LLM and embedding objects keyed by logical role (e.g. `get_llm("intent_parser")`, `get_embedder()`). Implementation pending in `src/totoro_ai/providers/`. Swapping a model means changing `models.yaml` only — no code changes.

**Consequences:** All LLM and embedding calls go through the abstraction. Adding a new provider requires only a new case in the factory function and a YAML entry. Implementation pending.

---

## ADR-019: FastAPI Depends() for database session and Redis client

**Date:** 2026-03-07

**Status:** accepted

**Context:** Endpoints for extract-place and consult both need a database connection and Redis client. Without dependency injection, each handler would manage its own connections, making testing and connection pooling harder.

**Decision:** Database session (SQLAlchemy async session or asyncpg connection) and Redis client are provided via FastAPI `Depends()`. Both dependencies are defined as async generators in `src/totoro_ai/api/deps.py`. Connection pools are created at app startup via lifespan events in `api/main.py`. Implementation pending.

**Consequences:** Handlers receive typed, lifecycle-managed connections. Tests can override dependencies via `app.dependency_overrides`. Implementation pending.

---

## ADR-018: Separate router modules for extract-place and consult

**Date:** 2026-03-07

**Status:** accepted

**Context:** Both endpoints are currently absent from the codebase. Placing them in `main.py` alongside the health check would conflate app bootstrap with business logic and make each endpoint harder to test in isolation.

**Decision:** Each endpoint lives in its own router module: `src/totoro_ai/api/routes/extract_place.py` and `src/totoro_ai/api/routes/consult.py`. Each module defines its own `APIRouter` with the `/v1` prefix inherited from the parent router in `main.py`. `main.py` includes both routers. Implementation pending.

**Consequences:** Endpoints are independently testable. Adding a third endpoint means adding a new file, not modifying existing ones. Implementation pending.

---

## ADR-017: Pydantic schemas for extract-place and consult request and response

**Date:** 2026-03-07

**Status:** accepted

**Context:** FastAPI validates request bodies and serializes response bodies. Without explicit Pydantic models, validation is implicit and the API contract has no enforceable shape in code.

**Decision:** All request and response bodies are Pydantic `BaseModel` subclasses defined in `src/totoro_ai/api/schemas.py`. Four models cover the two endpoints: `ExtractPlaceRequest`, `ExtractPlaceResponse`, `ConsultRequest`, `ConsultResponse`. Field names and types match the API contract in `docs/api-contract.md` exactly. Implementation pending.

**Consequences:** FastAPI returns 422 automatically for malformed requests. Response shapes are enforced at the boundary. Schema changes require updating both the Pydantic model and the API contract doc. Implementation pending.

---

## ADR-016: models.yaml logical-role-to-provider mapping

**Date:** 2026-03-07

**Status:** accepted

**Context:** The codebase must never hardcode model names. Provider switching must be a config change, not a code change. `config/models.yaml` was introduced as the single source of truth for this mapping.

**Decision:** `config/models.yaml` maps three logical roles — `intent_parser`, `orchestrator`, `embedder` — to provider name, model identifier, and inference parameters. Read at startup by `core/config.py:load_yaml_config("models.yaml")`. Current assignments: `intent_parser` → `openai/gpt-4o-mini`, `orchestrator` → `anthropic/claude-sonnet-4-6-20250514`, `embedder` → `voyage/voyage-3.5-lite`.

**Consequences:** Swapping any model requires one line change in `models.yaml`. Code that references model names by role rather than string literals is automatically correct after a config change. Adding a new role requires a new YAML entry and a new factory case in the provider layer.

---

## ADR-015: YAML config loader for non-secret settings

**Date:** 2026-03-07

**Status:** accepted

**Context:** Non-secret settings (app metadata, model assignments) must live in version-controlled files. Secrets must never appear in config files. A loader that knows where to find config files prevents hardcoded paths throughout the codebase.

**Decision:** `src/totoro_ai/core/config.py` exposes `load_yaml_config(name: str) -> dict` and `find_project_root() -> Path`. `find_project_root()` walks up from `__file__` until it finds `pyproject.toml`. `load_yaml_config` reads from `<project_root>/config/<name>`. Both `app.yaml` and `models.yaml` are loaded via this function.

**Consequences:** Config files are always found regardless of the working directory at runtime. Any module can call `load_yaml_config` without knowing the filesystem layout. Secrets must remain in environment variables — this loader never reads `.env` files.

---

## ADR-014: `/v1` API prefix via APIRouter loaded from app.yaml

**Date:** 2026-03-07

**Status:** accepted

**Context:** The API contract requires all endpoints under `/v1/`. The prefix must not be hardcoded in route decorators so it can be changed in one place if the versioning scheme changes.

**Decision:** `src/totoro_ai/api/main.py` creates an `APIRouter` with `prefix` loaded from `app.yaml` (`api_prefix: /v1`). All route decorators use paths relative to that prefix (e.g. `/health`, not `/v1/health`). The router is included in the FastAPI app via `app.include_router(router)`.

**Consequences:** All endpoints are versioned uniformly. Changing the prefix requires one line in `app.yaml`. New routers from other modules must also be included via `app.include_router` to inherit the convention.

---

## ADR-013: SSE streaming as future consult response mode
**Date:** 2026-03-05
**Status:** accepted
**Context:** The consult endpoint returns reasoning_steps in a synchronous JSON response. When the frontend needs to show agent thinking in real time, the API contract would need redesigning mid-build without a plan.
**Decision:** Document SSE as a future response mode now. When needed, FastAPI streams reasoning steps as they complete. The synchronous mode remains the default. No implementation until the frontend requires it.
**Consequences:** API contract is forward-compatible. NestJS will proxy the SSE stream when the time comes. No work needed today.

---

## ADR-012: reasoning_steps in consult response
**Date:** 2026-03-05
**Status:** accepted
**Context:** When a bad recommendation comes back, there is no way to tell if intent parsing failed, retrieval missed the right place, or ranking scored incorrectly. The eval pipeline also needs per-step accuracy measurement.
**Decision:** The consult response includes a `reasoning_steps` array. Each entry has a `step` identifier and a human-readable `summary` of what happened at that stage.
**Consequences:** Per-step debugging and evaluation become possible. The product repo consumes and renders these steps. Both repos' API contract docs updated.

---

## ADR-011: Minimal tool registration per consult request
**Date:** 2026-03-05
**Status:** accepted
**Context:** Each tool definition costs 100-300 tokens of static context per LLM call. Registering tools the agent never uses wastes tokens at scale.
**Decision:** Only register tools the agent needs for the current task. Do not preload tools for future capabilities.
**Consequences:** Saves 600-1,800 tokens per call when 6+ unused tools would otherwise be registered. Tool set must be evaluated per-request.

---

## ADR-010: Context budgeting between LangGraph nodes
**Date:** 2026-03-05
**Status:** accepted
**Context:** A raw Google Places response is ~2,000-4,000 tokens. Passing it through validation, ranking, and response generation means paying for those tokens 3 times in 3 LLM calls.
**Decision:** Each LangGraph node passes only the fields the next node needs. Extract relevant fields (name, address, price, distance, open status) and drop the rest.
**Consequences:** 80-90% reduction in wasted tokens on forwarded data. Nodes must explicitly define their input/output contracts.

---

## ADR-009: Parallel LangGraph branches for retrieval and discovery
**Date:** 2026-03-05
**Status:** accepted
**Context:** Retrieval (pgvector) and discovery (Google Places) are independent steps. Running sequentially wastes wall clock time against the 20s consult timeout.
**Decision:** Steps 2 (retrieve saved places) and 3 (discover external candidates) run as parallel LangGraph branches. Results merge before validation.
**Consequences:** ~43% latency reduction on those steps (7s sequential → 4s parallel). Frees ~3s of budget for ranking and response generation.

---

## ADR-008: extract-place is a workflow, not an agent
**Date:** 2026-03-05
**Status:** accepted
**Context:** extract-place follows a fixed sequence: parse input, validate via Google Places, generate embedding, write to DB. No tool selection or reasoning loop needed.
**Decision:** Implement extract-place as a sequential async function, not a LangGraph graph. Reserve LangGraph for consult where multi-step reasoning and tool selection are required.
**Consequences:** Cuts implementation complexity roughly in half. Eliminates graph-specific debugging (state schema, node ordering, conditional edges) for this endpoint.

---

## ADR-007: OpenAI embeddings first, Voyage later
**Date:** 2026-03-04
**Status:** accepted
**Context:** Need an embedding provider for place similarity search starting Phase 3.
**Decision:** Start with OpenAI embeddings (most documented API), swap to Voyage 3.5-lite in Phase 6 as a measurable optimization.
**Consequences:** Provider abstraction layer must support hot-swapping embedding providers via config.

---

## ADR-006: Python >=3.11,<3.13
**Date:** 2026-03-04
**Status:** accepted
**Context:** Need a Python version constraint for pyproject.toml.
**Decision:** Pin to >=3.11,<3.13. 3.11 minimum for AI library compatibility, upper bound protects against untested 3.13 changes.
**Consequences:** Must test on both 3.11 and 3.12. Revisit upper bound when 3.13 ecosystem stabilizes.

---

## ADR-005: Single config/models.yaml over split per-provider
**Date:** 2026-03-04
**Status:** accepted
**Context:** Need a config structure for the provider abstraction layer.
**Decision:** Single `config/models.yaml` mapping logical roles to provider + model + params. Only 3-4 models total — one file is readable, swap one line to switch providers.
**Consequences:** If model count grows significantly, revisit split structure. For now, simplicity wins.

---

## ADR-004: pytest in tests/ over co-located
**Date:** 2026-03-04
**Status:** accepted
**Context:** Need to decide where test files live.
**Decision:** Separate `tests/` directory mirroring `src/` structure. Clean separation, easier to navigate solo.
**Consequences:** Test discovery configured via pyproject.toml. Import paths must reference the installed package.

---

## ADR-003: Ruff + mypy over black/flake8
**Date:** 2026-03-04
**Status:** accepted
**Context:** Need linting and formatting tooling.
**Decision:** Ruff for lint + format (replaces black, isort, flake8 in one tool). mypy for strict type checking, especially important for Pydantic schema validation.
**Consequences:** Single `ruff.toml` or `[tool.ruff]` in pyproject.toml. `mypy --strict` as the target.

---

## ADR-002: Hybrid directory structure
**Date:** 2026-03-04
**Status:** accepted
**Context:** Need to organize modules inside `src/totoro_ai/`.
**Decision:** Hybrid layout: `api/` (FastAPI routes), `core/` (domain modules), `providers/` (LLM abstraction), `eval/` (evaluations). Balances domain clarity with clean entry points.
**Consequences:** Domain modules live under `core/` (intent, extraction, memory, ranking, taste, agent). Cross-cutting concerns like provider abstraction stay at the top level.

---

## ADR-001: src layout over flat layout
**Date:** 2026-03-04
**Status:** accepted
**Context:** Need to choose Python package layout.
**Decision:** src layout (`src/totoro_ai/`) per PEP 621. Prevents accidental local imports during testing.
**Consequences:** All imports use `totoro_ai.*`. Poetry and pytest configured to find packages under `src/`.
