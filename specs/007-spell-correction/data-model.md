# Data Model: Spell Correction Pipeline

**Feature**: 007-spell-correction
**Date**: 2026-03-31

## No schema changes

This feature introduces no new database tables, no Alembic migrations, and no new Pydantic request/response schema fields. All changes are internal to service layer processing.

## Config extension

### `SpellCorrectionConfig` (Pydantic model in `core/config.py`)

| Field      | Type  | Default      | Description                                       |
|------------|-------|--------------|---------------------------------------------------|
| `provider` | `str` | `"symspell"` | Name of the active corrector; read by the factory |

Mapped from `config/app.yaml` under `spell_correction:`.

## Protocol

### `SpellCorrectorProtocol` (in `core/spell_correction/base.py`)

| Method  | Signature                                      | Description                                                                      |
|---------|------------------------------------------------|----------------------------------------------------------------------------------|
| correct | `(text: str, language: str = "en") -> str`     | Return corrected text. Return original unchanged on any error. Never raises.     |

## SymSpellCorrector state

### `SymSpellCorrector` (in `core/spell_correction/symspell.py`)

Internal state (not exposed externally):

| Attribute          | Type         | Description                                          |
|--------------------|--------------|------------------------------------------------------|
| `_sym_spell`       | `SymSpell`   | Loaded SymSpell instance with English dictionary     |
| `_max_edit_distance` | `int`      | Maximum edit distance for correction (default: 2)    |

Loaded once at construction time. The dictionary is the bundled `frequency_dictionary_en_82_765.txt` from the `symspellpy` package.

## Service constructor changes (dependency injection)

| Service           | New parameter         | Type                   |
|-------------------|-----------------------|------------------------|
| `ExtractionService` | `spell_corrector`   | `SpellCorrectorProtocol` |
| `ConsultService`    | `spell_corrector`   | `SpellCorrectorProtocol` |
| `RecallService`     | `spell_corrector`   | `SpellCorrectorProtocol` |

No changes to request/response schemas. The correction is invisible to callers.

## Data flow per endpoint

### POST /v1/extract-place

```
raw_input (str)
  │
  ▼ spell_corrector.correct(raw_input)  ← NEW, first step
  │
  ▼ dispatcher.dispatch(corrected_input)
  │
  ▼ extractor → places validation → confidence → DB write
```

### POST /v1/consult

```
query (str)
  │
  ▼ spell_corrector.correct(query)  ← NEW, first step
  │
  ▼ IntentParser.parse(corrected_query)
  │
  ▼ LLM recommendation generation
```

### POST /v1/recall

```
query (str)
  │
  ▼ spell_corrector.correct(query)  ← NEW, first step
  │
  ▼ embedder.embed(corrected_query)
  │
  ▼ hybrid search (vector + FTS)
```
