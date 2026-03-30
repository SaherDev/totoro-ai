# Quickstart: Spell Correction Pipeline

**Feature**: 007-spell-correction

## What changed

Three service constructors receive a new `spell_corrector: SpellCorrectorProtocol` argument. Each service calls `spell_corrector.correct(text)` as its first step. `config/app.yaml` gains a `spell_correction.provider: symspell` key. `symspellpy` is added as a Poetry dependency.

## Running the service

```bash
poetry install              # picks up symspellpy
docker compose up -d        # PostgreSQL + Redis
poetry run uvicorn totoro_ai.api.main:app --reload
```

## Testing spell correction

```bash
# Unit tests
poetry run pytest tests/core/spell_correction/ -v

# All tests
poetry run pytest

# Type check
poetry run mypy src/

# Lint
poetry run ruff check src/ tests/
```

## Swapping the corrector

1. Open `config/app.yaml`
2. Change `spell_correction.provider: symspell` to the new provider name (e.g., `pyspellchecker`)
3. Ensure a `PySpellCheckerCorrector` class exists in `src/totoro_ai/core/spell_correction/` and is registered in the factory
4. Restart the service — no code change needed in route handlers or service layers

## Adding a language-specific corrector

1. Create a new class in `src/totoro_ai/core/spell_correction/` implementing `SpellCorrectorProtocol`
2. Add the new provider name to the factory's dispatch table in `src/totoro_ai/providers/spell_correction.py`
3. Update `config/app.yaml` to reference it

## Bruno test requests

Three new requests in `totoro-config/bruno/ai-service/`:
- `extract-place-typo.bru` — sends `"fuji raman shope in sukhumvit"`, verifies 200 response
- `consult-typo.bru` — sends `"cheep diner nerby"`, verifies 200 + primary recommendation
- `recall-typo.bru` — sends `"raman place"`, verifies 200 + results array

After running each request, verify the stored record in the DB has the corrected text, not the raw typo:

```sql
SELECT place_name FROM places ORDER BY created_at DESC LIMIT 1;
-- Expected: "Fuji Ramen" (not "fuji raman shope in sukhumvit")
```
