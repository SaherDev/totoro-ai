# Research: Spell Correction Pipeline

**Feature**: 007-spell-correction
**Date**: 2026-03-31

## 1. symspellpy Dictionary Loading

**Decision**: Use `symspellpy`'s bundled `frequency_dictionary_en_82_765.txt`, loaded via `importlib.resources.files("symspellpy")` (Python 3.11 native API).

**Rationale**: symspellpy ships the English frequency dictionary in its package data. No external download needed. `importlib.resources` is the Python 3.9+ standard; `pkg_resources` is deprecated and must NOT be used.

**Alternatives considered**:
- `pkg_resources.resource_filename(...)`: deprecated since Python 3.9, removed path in 3.12+; rejected
- Custom dictionary file: more accurate for food/restaurant domain but requires maintenance; deferred
- Download at runtime: adds latency and network dependency; rejected

**Usage**:
```python
from importlib.resources import files
from symspellpy import SymSpell

sym_spell = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
dict_path = files("symspellpy").joinpath("frequency_dictionary_en_82_765.txt")
sym_spell.load_dictionary(str(dict_path), term_index=0, count_index=1)
```

## 2. URL Preservation

**Decision**: Tokenise input on whitespace; apply `urllib.parse.urlparse` to each token; skip tokens where `scheme` is `http` or `https`; join corrected tokens back.

**Rationale**: SymSpell operates on individual terms. By skipping URL tokens before correction, TikTok URLs (e.g., `https://tiktok.com/@foodie/video/123`) are never passed to the corrector and cannot be mangled. This handles the mixed-input case (URL + surrounding text) transparently.

**Alternatives considered**:
- Regex URL detection: more fragile than `urllib.parse`; rejected
- Full input correction without URL awareness: corrupts URLs; rejected

## 3. Error Fallback

**Decision**: Wrap `correct()` body in a broad `try/except Exception`. On any error, log a warning and return the original text unchanged.

**Rationale**: Spell correction must never crash a request (spec FR-006). A dictionary load failure, unexpected token, or runtime error in symspellpy must degrade gracefully. The request proceeds with uncorrected text.

## 4. Config Location

**Decision**: `spell_correction.provider: symspell` in `config/app.yaml` (non-secret).

**Rationale**: Per ADR-029, all non-secret config lives in `config/app.yaml`. The provider name is not a secret. This is consistent with how `models.embedder.provider: voyage` is configured.

**Alternatives considered**:
- `config/.local.yaml`: reserved for secrets; rejected
- Hardcoded default: not swappable via config; rejected per ADR-032 and ADR-038

## 5. Injection Pattern + Singleton

**Decision**: Constructor injection in all three services. `get_spell_corrector()` is decorated with `@functools.lru_cache(maxsize=1)` — it constructs the `SymSpellCorrector` once on the first call and returns the cached instance on every subsequent call, including per-request `Depends()` invocations.

**Rationale**: `SymSpellCorrector.__init__` loads a 29 MB dictionary from disk. Creating a new instance per request would incur a 29 MB file read on every API call, causing severe latency regression. `@lru_cache` is the idiomatic Python singleton pattern: zero-boilerplate, thread-safe for read-only state, and compatible with FastAPI's `Depends()`. The instance is stateless after construction (no mutable request-scoped state), so sharing it across requests is safe.

**Alternatives considered**:
- FastAPI `lifespan` + `app.state`: valid but more complex wiring; lru_cache is simpler for a stateless singleton
- Module-level global: less explicit; lru_cache communicates intent more clearly

**Critical constraint**: Do NOT construct `SymSpellCorrector` inside a non-cached callable. The `Depends(get_spell_corrector)` call in `deps.py` is safe only because `get_spell_corrector` is `@lru_cache`-wrapped.

## 6. Language Resolution

**Decision**: Default to `"en"` for all requests in this iteration. User locale from DB is deferred.

**Rationale**: No existing mechanism to look up user locale in the services. The spec's Assumptions section documents this. SymSpellCorrector accepts a `language` parameter so the interface is forward-compatible — adding locale resolution means updating `deps.py` to pass the locale string, not changing the Protocol or implementation.

## 7. Correction Scope — Extract-Place

**Decision**: Apply `spell_corrector.correct(raw_input)` to the full `raw_input` string at the top of `ExtractionService.run()`, before dispatching to extractors.

**Rationale**: The corrector preserves URLs internally (decision 2 above). Applying to the whole string before dispatch is simpler than splitting input first. The dispatcher and extractors see pre-corrected text/supplementary context, which improves LLM extraction accuracy.

**Consequence**: For TikTok URL inputs, the URL is preserved; any surrounding text ("fuji raman shope") is corrected before the LLM extractor sees it.

## 8. symspellpy compound correction

**Decision**: Use `lookup_compound()` for multi-word inputs (queries, plain text descriptions).

**Rationale**: `lookup_compound()` handles phrase-level correction and word boundary errors (e.g., "fuji raman" → "fuji ramen"). `lookup()` only corrects single words. For the consult and recall query use case, phrase-level correction is more useful.

**Usage**:
```python
suggestions = sym_spell.lookup_compound(text, max_edit_distance=2)
return suggestions[0].term if suggestions else text
```
