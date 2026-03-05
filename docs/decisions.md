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
