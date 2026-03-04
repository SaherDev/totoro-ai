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
