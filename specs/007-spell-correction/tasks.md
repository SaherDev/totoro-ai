# Tasks: Spell Correction Pipeline

**Input**: Design documents from `/specs/007-spell-correction/`
**Branch**: `007-spell-correction`

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no shared dependencies)
- **[Story]**: User story this task belongs to (US1–US4)
- No test tasks — not requested in spec

---

## Phase 1: Setup

**Purpose**: Add the dependency and extend config before writing any Python logic.

- [X] T001 Add `symspellpy = "^0.0.8"` (or latest) to `[tool.poetry.dependencies]` in `pyproject.toml` and run `poetry install`
- [X] T002 Add `spell_correction:\n  provider: symspell` section to `config/app.yaml` (after the `recall:` block)
- [X] T003 Add `SpellCorrectionConfig(BaseModel)` with field `provider: str = "symspell"` and add `spell_correction: SpellCorrectionConfig = SpellCorrectionConfig()` to `AppConfig` in `src/totoro_ai/core/config.py`

**Checkpoint**: `poetry run python -c "from totoro_ai.core.config import get_config; print(get_config().spell_correction)"` prints the config without error.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Protocol + concrete implementation + singleton factory. All four user stories depend on this phase. No user story work can begin until T004–T009 are complete.

**⚠️ CRITICAL**: `SymSpellCorrector.__init__` loads a 29 MB dictionary. The factory MUST use `@functools.lru_cache(maxsize=1)` — never construct per-request.

- [X] T004 Create `src/totoro_ai/core/spell_correction/__init__.py` (empty)
- [X] T005 [P] Create `src/totoro_ai/core/spell_correction/base.py` — define `SpellCorrectorProtocol` as a `@runtime_checkable` `Protocol` with one method: `def correct(self, text: str, language: str = "en") -> str: ...` — follow the pattern in `src/totoro_ai/providers/embeddings.py`
- [X] T006 Create `src/totoro_ai/core/spell_correction/symspell.py` — implement `SymSpellCorrector` wrapping `symspellpy`:
  - Load dictionary via `importlib.resources.files("symspellpy").joinpath("frequency_dictionary_en_82_765.txt")` — do NOT use `pkg_resources`
  - Use `lookup_compound(text, max_edit_distance=2)` for multi-word correction
  - Tokenise on whitespace; skip tokens where `urllib.parse.urlparse(token).scheme in ("http", "https")` to preserve URLs
  - Wrap entire `correct()` body in `try/except Exception`: on any error, log a warning and return original `text` unchanged
  - `language` parameter accepted but unused in this iteration (always English)
- [X] T007 Create `src/totoro_ai/providers/spell_correction.py` — implement `get_spell_corrector()` decorated with `@functools.lru_cache(maxsize=1)`:
  - Read `get_config().spell_correction.provider`
  - `"symspell"` → return `SymSpellCorrector()`
  - Unknown provider → raise `ValueError(f"Unsupported spell correction provider: {provider}")`
  - Return type annotated as `SpellCorrectorProtocol`
- [X] T008 [P] Create `tests/core/spell_correction/__init__.py` (empty) and `tests/core/spell_correction/test_symspell.py` — unit tests for `SymSpellCorrector`:
  - `test_corrects_common_typo`: `"cheep diner nerby"` → corrected string contains no original typos
  - `test_preserves_url_token`: input containing `https://tiktok.com/...` returns URL token unchanged
  - `test_preserves_unknown_proper_noun`: an invented restaurant name not in dictionary is returned unchanged
  - `test_fallback_on_error`: patch internal `_sym_spell` to raise; `correct()` returns original text without raising
  - `test_no_mutation_on_clean_input`: correctly-spelled input returns unchanged
- [X] T009 [P] Create `tests/providers/__init__.py` (if absent) and `tests/providers/test_spell_correction.py` — factory tests:
  - `test_returns_spell_corrector_protocol`: `get_spell_corrector()` returns an instance satisfying `SpellCorrectorProtocol`
  - `test_singleton_same_instance`: two calls to `get_spell_corrector()` return the exact same object (`is`)
  - `test_unknown_provider_raises`: override config to use an unknown provider string; assert `ValueError` raised
  - Clear `lru_cache` between tests using `get_spell_corrector.cache_clear()`

**Checkpoint**: `poetry run pytest tests/core/spell_correction/ tests/providers/test_spell_correction.py -v` — all pass. `poetry run mypy src/totoro_ai/core/spell_correction/ src/totoro_ai/providers/spell_correction.py` — no errors.

---

## Phase 3: User Story 1 — Typo-tolerant place saving (Priority: P1) 🎯 MVP

**Goal**: Spell correction fires before place extraction so typos in plain-text place names reach the LLM extractor in corrected form, leading to better Google Places matches and higher-quality stored records.

**Independent Test**: Run `extract-place-typo.bru` against the local server. Verify HTTP 200 and the response `place.place_name` is a recognisable, correctly-spelled place name — not the raw typo string.

- [X] T010 [US1] Add `spell_corrector: SpellCorrectorProtocol` to `ExtractionService.__init__` parameters and store as `self._spell_corrector` in `src/totoro_ai/core/extraction/service.py`; add call `raw_input = self._spell_corrector.correct(raw_input)` as the very first line of `run()` (before the empty-string validation)
- [X] T011 [US1] Wire `spell_corrector=get_spell_corrector()` into the `ExtractionService(...)` constructor call inside `get_extraction_service()` in `src/totoro_ai/api/deps.py`; add the import for `get_spell_corrector`
- [X] T012 [US1] Create `totoro-config/bruno/ai-service/extract-place-typo.bru` — POST `/v1/extract-place` with body `{"user_id": "<test_user_id>", "raw_input": "fuji raman shope in sukhumvit"}` — include Bruno tests: status 200, `place.place_name` exists and is a non-empty string

**Checkpoint**: `POST /v1/extract-place` with `"fuji raman shope in sukhumvit"` returns 200 and a recognisable place name. Existing `tests/api/test_extract_place.py` still passes.

---

## Phase 4: User Story 2 — Typo-tolerant consultation queries (Priority: P1)

**Goal**: Spell correction fires before intent parsing so typos in consult queries (e.g., "cheep diner nerby") reach the LLM intent parser as corrected text, improving structured extraction of price, cuisine, and location constraints.

**Independent Test**: Run `consult-typo.bru` against the local server. Verify HTTP 200 and the response includes a `primary` recommendation with a non-empty `place_name`.

- [X] T013 [P] [US2] Read `src/totoro_ai/api/routes/consult.py` to determine how `ConsultService` is currently constructed (direct instantiation in handler or via a dep in `deps.py`); then add `spell_corrector: SpellCorrectorProtocol` to `ConsultService.__init__` and call `query = self._spell_corrector.correct(query)` as the first line of `consult()` (before `IntentParser.parse(query)`) in `src/totoro_ai/core/consult/service.py`
- [X] T014 [US2] Wire `spell_corrector=get_spell_corrector()` into `ConsultService` construction — either in `deps.py` if a `get_consult_service` dependency exists, or in the route handler's `ConsultService(...)` call in `src/totoro_ai/api/routes/consult.py`; add the import for `get_spell_corrector`
- [X] T015 [US2] Create `totoro-config/bruno/ai-service/consult-typo.bru` — POST `/v1/consult` with body `{"user_id": "<test_user_id>", "query": "cheep diner nerby", "location": {"lat": 13.7563, "lng": 100.5018}}` — include Bruno tests: status 200, `primary.place_name` is a non-empty string, `reasoning_steps` array is present

**Checkpoint**: `POST /v1/consult` with `"cheep diner nerby"` returns 200 with a primary recommendation. Existing `tests/api/test_consult.py` and `tests/core/consult/test_service.py` still pass.

---

## Phase 5: User Story 3 — Typo-tolerant recall searches (Priority: P2)

**Goal**: Spell correction fires before query embedding in the recall pipeline so typos in memory fragment queries produce corrected embeddings, improving vector similarity match against correctly-spelled stored records.

**Independent Test**: Run `recall-typo.bru` against the local server. Verify HTTP 200 and the `results` array is present (may be empty if no places saved yet, but must not be an error).

- [X] T016 [P] [US3] Add `spell_corrector: SpellCorrectorProtocol` to `RecallService.__init__` parameters and store as `self._spell_corrector` in `src/totoro_ai/core/recall/service.py`; add call `query = self._spell_corrector.correct(query)` as the first line of `run()` (before the cold-start check)
- [X] T017 [US3] Wire `spell_corrector=get_spell_corrector()` into the `RecallService(...)` constructor call inside `get_recall_service()` in `src/totoro_ai/api/deps.py`; add the import for `get_spell_corrector`
- [X] T018 [US3] Create `totoro-config/bruno/ai-service/recall-typo.bru` — POST `/v1/recall` with body `{"user_id": "<test_user_id>", "query": "raman place from tiktok"}` — include Bruno tests: status 200, `results` array exists, `total` is a number

**Checkpoint**: `POST /v1/recall` with `"raman place from tiktok"` returns 200. Existing `tests/api/routes/test_recall.py` and `tests/core/recall/test_service.py` still pass.

---

## Phase 6: User Story 4 — Swappable corrector (Priority: P2)

**Goal**: Confirm the factory dispatch and error path work correctly so an operator can swap providers via a single config value. The Protocol and factory were built in Phase 2; this phase validates and locks the contract.

**Independent Test**: Verify `get_spell_corrector.cache_clear()` + config override to an unknown provider raises `ValueError`. Verify config set to `"symspell"` returns a `SpellCorrectorProtocol`-conformant instance.

- [X] T019 [US4] Confirm `tests/providers/test_spell_correction.py` (written in T009) covers: (a) `"symspell"` → `SymSpellCorrector` instance, (b) unknown provider string → `ValueError`, (c) two calls → same instance. Add any missing cases. No new files needed if T009 is already complete.

**Checkpoint**: `poetry run pytest tests/providers/test_spell_correction.py -v` — all pass, including unknown-provider and singleton cases.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T020 [P] Run `poetry run ruff check src/ tests/` — fix any lint errors introduced by new files
- [X] T021 [P] Run `poetry run mypy src/` — fix any type errors in new and modified files; ensure `SpellCorrectorProtocol` satisfies `@runtime_checkable` check against `SymSpellCorrector`
- [X] T022 Run `poetry run pytest` — verify all pre-existing tests still pass alongside the new spell correction tests; fix any regressions
- [X] T023 [P] Update `docs/decisions.md` ADR-032 consequences section to note implementation is complete and point to the new module paths (`src/totoro_ai/core/spell_correction/`, `src/totoro_ai/providers/spell_correction.py`)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 (T001–T003) — BLOCKS all user story phases
- **Phase 3 (US1)**: Depends on Phase 2 completion
- **Phase 4 (US2)**: Depends on Phase 2 completion — can run in parallel with Phase 3
- **Phase 5 (US3)**: Depends on Phase 2 completion — can run in parallel with Phases 3 & 4
- **Phase 6 (US4)**: Depends on Phase 2 completion (T009 already covers most of it)
- **Phase 7 (Polish)**: Depends on all desired story phases being complete

### Within Phase 2

```
T004 (init file) → T005, T006 can start
T005 [P] ← SpellCorrectorProtocol (no deps)
T006 ← SymSpellCorrector (no deps on T005 at file level)
T007 ← depends on T005 (imports Protocol) and T006 (imports SymSpellCorrector)
T008 [P] ← can start after T006
T009 [P] ← can start after T007
```

### Parallel Opportunities

```bash
# Phase 2 — launch in parallel after T004:
Task T005: "Create SpellCorrectorProtocol in src/totoro_ai/core/spell_correction/base.py"
Task T006: "Create SymSpellCorrector in src/totoro_ai/core/spell_correction/symspell.py"

# Phase 2 — launch in parallel after T007:
Task T008: "Create tests/core/spell_correction/test_symspell.py"
Task T009: "Create tests/providers/test_spell_correction.py"

# Phases 3, 4, 5 — launch in parallel after Phase 2 completes:
Task T010–T012: User Story 1 (extract-place)
Task T013–T015: User Story 2 (consult)
Task T016–T018: User Story 3 (recall)

# Phase 7 — launch in parallel:
Task T020: ruff check
Task T021: mypy
Task T023: docs update
```

---

## Implementation Strategy

### MVP (User Story 1 only)

1. Complete Phase 1: Setup (T001–T003)
2. Complete Phase 2: Foundational (T004–T009)
3. Complete Phase 3: US1 extract-place (T010–T012)
4. **STOP and VALIDATE**: `poetry run pytest` passes; Bruno `extract-place-typo.bru` returns 200 with corrected place name
5. Correct foundation is now proven; extend to US2 and US3

### Incremental Delivery

1. Phase 1 + Phase 2 → corrector module complete and tested
2. Add Phase 3 (US1) → typo-tolerant place saving live
3. Add Phase 4 (US2) → typo-tolerant consult queries live
4. Add Phase 5 (US3) → typo-tolerant recall live
5. Phase 6 + Phase 7 → swappability verified, full suite clean

---

## Notes

- `SymSpellCorrector` is a singleton — `get_spell_corrector()` uses `@lru_cache(maxsize=1)`. Tests must call `get_spell_corrector.cache_clear()` in teardown to avoid cross-test contamination.
- `importlib.resources.files("symspellpy")` — never `pkg_resources`.
- Correction is always `language="en"` for this iteration. The `language` parameter exists on the Protocol for forward compatibility.
- URL tokens (scheme `http`/`https`) must never be passed to SymSpell's corrector — tokenise on whitespace, skip URL tokens, rejoin.
- Commit after each phase checkpoint to keep history clean.
