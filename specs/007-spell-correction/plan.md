# Implementation Plan: Spell Correction Pipeline

**Branch**: `007-spell-correction` | **Date**: 2026-03-31 | **Spec**: [spec.md](./spec.md)

## Summary

Add a swappable spell correction layer (Protocol + SymSpell implementation) that silently corrects typos in user input before any parsing, embedding, or LLM call across all three endpoints (extract-place, consult, recall). The active corrector is loaded from `config/app.yaml` under `spell_correction.provider`. Swapping correctors requires only a config change. Language defaults to `"en"` (with DB-resident user locale as a future enhancement).

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**: FastAPI 0.115, Pydantic 2.10, SQLAlchemy 2.0 async, symspellpy (new)
**Storage**: PostgreSQL — no schema changes needed
**Testing**: pytest with asyncio_mode=auto
**Target Platform**: Linux server (Railway)
**Project Type**: Python web-service (src layout)
**Performance Goals**: Correction < 2ms total per request (SymSpell: 0.033ms/word at edit distance 2)
**Constraints**: Correction never fails a request; fallback to raw input on any error
**Scale/Scope**: One new module + 3 constructor injections + config extension

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Rule | Check | Notes |
|------|-------|-------|
| ADR-001: src layout | ✅ PASS | New files in `src/totoro_ai/core/spell_correction/` and `src/totoro_ai/providers/` |
| ADR-002: hybrid dir | ✅ PASS | Protocol + impl in `core/spell_correction/`, factory in `providers/spell_correction.py` |
| ADR-003: ruff + mypy strict | ✅ PASS | All new code must pass `ruff check` and `mypy --strict` |
| ADR-004: pytest in tests/ | ✅ PASS | Test files mirror src structure under `tests/core/spell_correction/` |
| ADR-008: extract-place not LangGraph | ✅ PASS | No LangGraph involved |
| ADR-014: /v1 prefix via APIRouter | ✅ PASS | No new routes added |
| ADR-017: Pydantic everywhere | ✅ PASS | No raw dicts at function boundaries |
| ADR-018: separate router modules | ✅ PASS | No route changes |
| ADR-019: Depends() only | ✅ PASS | SpellCorrector injected via `Depends()` in `deps.py` |
| ADR-020: provider abstraction | ✅ PASS | Factory reads `spell_correction.provider` from config, never hardcodes |
| ADR-025: Langfuse on LLM calls | ✅ PASS | Spell correction is pure function — no LLM call, no tracing needed |
| ADR-029: app.yaml for non-secrets | ✅ PASS | `spell_correction.provider: symspell` lives in `config/app.yaml` |
| ADR-034: facade pattern on routes | ✅ PASS | No business logic added to route handlers |
| ADR-038: Protocol abstraction | ✅ PASS | `SpellCorrectorProtocol` defined first; services depend on Protocol only |
| ADR-044: prompt injection mitigation | ✅ PASS | No LLM call injecting retrieved content here |
| Constitution VI: DB write ownership | ✅ PASS | No schema changes, no new table writes |

**Post-design re-check**: No violations found. Plan is Constitution-clean.

## Project Structure

### Documentation (this feature)

```text
specs/007-spell-correction/
├── plan.md              ← this file
├── research.md          ← Phase 0 output
├── data-model.md        ← Phase 1 output
├── contracts/           ← Phase 1 output
└── tasks.md             ← /speckit.tasks output (not yet created)
```

### Source Code Changes

```text
src/totoro_ai/
├── core/
│   └── spell_correction/               ← NEW module
│       ├── __init__.py
│       ├── base.py                     ← SpellCorrectorProtocol (Protocol)
│       └── symspell.py                 ← SymSpellCorrector (wraps symspellpy)
├── providers/
│   └── spell_correction.py             ← NEW: factory get_spell_corrector()
└── core/
    ├── config.py                       ← MODIFIED: add SpellCorrectionConfig + AppConfig.spell_correction
    ├── extraction/service.py           ← MODIFIED: inject + call corrector as first step
    ├── consult/service.py              ← MODIFIED: inject + call corrector before intent parsing
    └── recall/service.py               ← MODIFIED: inject + call corrector before embedding
├── api/
│   └── deps.py                         ← MODIFIED: wire spell corrector into all three service deps

config/
└── app.yaml                            ← MODIFIED: add spell_correction.provider: symspell

pyproject.toml                          ← MODIFIED: add symspellpy dependency

tests/
├── core/
│   └── spell_correction/               ← NEW
│       ├── __init__.py
│       ├── test_base.py                ← Protocol conformance test
│       └── test_symspell.py            ← SymSpellCorrector unit tests
└── providers/
    ├── __init__.py                     ← NEW (if not exists)
    └── test_spell_correction.py        ← factory test

totoro-config/bruno/ai-service/
├── extract-place-typo.bru              ← NEW: typo input to extract-place
├── consult-typo.bru                    ← NEW: typo query to consult
└── recall-typo.bru                     ← NEW: typo query to recall
```

## Phase 0: Research

*Resolved; no open unknowns blocking implementation.*

See [research.md](./research.md) for full findings.

Key resolved decisions:
- **SymSpellCorrector dictionary**: Use symspellpy's bundled `frequency_dictionary_en_82_765.txt`, loaded via `importlib.resources.files("symspellpy")` (Python 3.11+). Do NOT use `pkg_resources` — it is deprecated.
- **URL preservation**: Apply correction only to non-URL tokens; detect URLs via `urllib.parse.urlparse` before correcting
- **Language resolution**: Always `"en"` for this iteration; locale-aware path is deferred (per clarification)
- **Config location**: `spell_correction.provider` in `config/app.yaml` (non-secret, per ADR-029)
- **Singleton — CRITICAL**: `SymSpellCorrector` loads a 29 MB dictionary on `__init__`. It MUST be constructed once at startup, not per-request. Use `@functools.lru_cache` on the factory so the first call constructs and caches the instance; all subsequent calls (including per-request `Depends()`) return the cached singleton. Do NOT construct inside route handlers or per-request dependency callables without caching.
- **Injection point**: `Depends(get_spell_corrector)` in `deps.py` where `get_spell_corrector` is `@lru_cache`-wrapped — returns the same singleton every call
- **Protocol**: `runtime_checkable` Protocol matching `embeddings.py` pattern (ADR-038)

## Phase 1: Design & Contracts

### Spell Corrector Protocol

```python
# src/totoro_ai/core/spell_correction/base.py
from typing import Protocol, runtime_checkable

@runtime_checkable
class SpellCorrectorProtocol(Protocol):
    def correct(self, text: str, language: str = "en") -> str:
        """Return corrected text. Original returned unchanged on any error."""
        ...
```

### SymSpellCorrector

```python
# src/totoro_ai/core/spell_correction/symspell.py
class SymSpellCorrector:
    """Wraps symspellpy. URLs in text are preserved unchanged."""

    def __init__(self, max_edit_distance: int = 2) -> None: ...
    def correct(self, text: str, language: str = "en") -> str: ...

    def _correct_non_url_tokens(self, text: str) -> str:
        """Split on whitespace, skip URL tokens, correct the rest."""
        ...
```

### Factory

```python
# src/totoro_ai/providers/spell_correction.py
import functools

@functools.lru_cache(maxsize=1)
def get_spell_corrector() -> SpellCorrectorProtocol:
    """Singleton factory — constructed once at first call, cached forever.

    SymSpellCorrector loads a 29 MB dictionary on __init__. lru_cache ensures
    this happens exactly once per process, not once per request.
    Reads spell_correction.provider from app.yaml.
    """
    ...
```

### Config Extension

```python
# New in src/totoro_ai/core/config.py
class SpellCorrectionConfig(BaseModel):
    provider: str = "symspell"

# Extend AppConfig:
class AppConfig(BaseModel):
    ...
    spell_correction: SpellCorrectionConfig = SpellCorrectionConfig()
```

```yaml
# config/app.yaml addition
spell_correction:
  provider: symspell
```

### Service wiring

**ExtractionService** (`core/extraction/service.py`):
- Add `spell_corrector: SpellCorrectorProtocol` to `__init__`
- In `run()`, before Step 2 (dispatch):
  ```python
  raw_input = self._spell_corrector.correct(raw_input)
  ```
  (The corrector handles URL preservation internally via token-level detection.)

**ConsultService** (`core/consult/service.py`):
- Add `spell_corrector: SpellCorrectorProtocol` to `__init__`
- In `consult()`, before `IntentParser.parse(query)`:
  ```python
  query = self._spell_corrector.correct(query)
  ```

**RecallService** (`core/recall/service.py`):
- Add `spell_corrector: SpellCorrectorProtocol` to `__init__`
- In `run()`, before `self._embedder.embed([query], ...)`:
  ```python
  query = self._spell_corrector.correct(query)
  ```

**deps.py** — add to all three dependency builders:
```python
from totoro_ai.providers.spell_correction import get_spell_corrector

def get_extraction_service(...) -> ExtractionService:
    return ExtractionService(
        ...,
        spell_corrector=get_spell_corrector(),
    )
```

### Bruno test format

Three new `.bru` files in `totoro-config/bruno/ai-service/`:
- `extract-place-typo.bru` — body: `{"user_id": "...", "raw_input": "fuji raman shope in sukhumvit"}` — test: `place_name` in response not equal to raw typo
- `consult-typo.bru` — body: `{"user_id": "...", "query": "cheep diner nerby", "location": {...}}` — test: response status 200, has primary
- `recall-typo.bru` — body: `{"user_id": "...", "query": "raman place"}` — test: response status 200, results array present

## Complexity Tracking

No constitution violations. No complexity table needed.
