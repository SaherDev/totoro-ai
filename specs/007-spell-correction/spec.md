# Feature Specification: Spell Correction Pipeline

**Feature Branch**: `007-spell-correction`
**Created**: 2026-03-31
**Status**: Draft

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Typo-tolerant place saving (Priority: P1)

A user types a place name with a spelling mistake when sharing a place (e.g., "fuji raman"). Without correction, the embedding drifts and the place becomes hard to find later. With correction, the system silently fixes "raman" → "ramen" before storing the record, so future searches for "ramen spots" surface it correctly.

**Why this priority**: Every saved place record depends on correct text for embedding quality. A drifted embedding directly harms recall accuracy — the most important retrieval metric for the product.

**Independent Test**: Send a `POST /v1/extract-place` request with a typo-laden plain text input (e.g., `"fuji raman shope in sukhumvit"`). Verify the stored `place_name` in the database is a recognisable, correctly-spelled place name (the corrected text feeds the LLM extractor → better Google Places match → validated name stored).

**Acceptance Scenarios**:

1. **Given** a user submits `"fuji raman"` to extract-place, **When** the request is processed, **Then** the corrected text reaches the LLM extractor, producing a better Google Places match, and the stored `place_name` is the Google-validated name of the correct place.
2. **Given** a user submits a correctly spelled input, **When** the request is processed, **Then** the output is identical to the original input with no unintended mutations.
3. **Given** a user submits a proper noun that is not in the dictionary (e.g., an unusual restaurant name), **When** the request is processed, **Then** the corrector preserves the term unchanged rather than corrupting it.

---

### User Story 2 - Typo-tolerant consultation queries (Priority: P1)

A user types a natural language query with typos (e.g., "cheep diner nerby"). Without correction, the intent parser may misread "cheep" as a non-price term and "nerby" as unknown. With correction, the system silently fixes the input before intent parsing, so the engine correctly extracts price=low, type=diner, and radius=nearby.

**Why this priority**: Typos in consult queries degrade intent parsing accuracy. A misread price constraint or cuisine type directly causes wrong recommendations — the primary output quality metric.

**Independent Test**: Send a `POST /v1/consult` request with a typo-laden query. Verify via Langfuse traces or response `reasoning_steps` that the intent was correctly parsed (e.g., price=low extracted), confirming corrected text reached the parser.

**Acceptance Scenarios**:

1. **Given** a user submits `"cheep diner nerby"` to consult, **When** the request is processed, **Then** intent parsing receives the corrected query and extracts price=low correctly.
2. **Given** a user submits a query in a language other than English, **When** the request is processed, **Then** the English corrector runs; unrecognised non-English terms are preserved unchanged (locale-aware correction is deferred).
3. **Given** the spell corrector service is misconfigured, **When** a request arrives, **Then** the system falls back to passing the raw input through rather than failing the request.

---

### User Story 3 - Typo-tolerant recall searches (Priority: P2)

A user types a memory fragment with a typo (e.g., "that raman place from tiktok"). Without correction, the query embedding is based on the misspelled word and may miss the correctly-spelled saved record. With correction, the query is cleaned before embedding, improving the chance of a vector match against the stored place.

**Why this priority**: Recall accuracy directly affects whether users can find their saved places. Lower priority than P1 stories only because recall has a fallback FTS path that can compensate for some embedding mismatches.

**Independent Test**: Save a place named "Fuji Ramen", then send a `POST /v1/recall` with query `"that raman place"`. Verify the corrected query ("that ramen place") is embedded and the saved place appears in results.

**Acceptance Scenarios**:

1. **Given** a user saved a place named "Fuji Ramen" and submits `"that raman place"` to recall, **When** the request is processed, **Then** the corrected query is embedded and the saved place appears in results.
2. **Given** a recall query with no typos, **When** the request is processed, **Then** the query passes through unchanged and results are equivalent to the uncorrected path.

---

### User Story 4 - Swappable corrector without code changes (Priority: P2)

An operator wants to swap from the default spell correction library to an alternative (e.g., for a language-specific dictionary or a higher-accuracy option). They change one value in the configuration file and restart the service. No application code changes are needed.

**Why this priority**: This is an operational requirement that protects long-term flexibility. Not urgent for users but critical for maintainability as the product expands to new languages.

**Independent Test**: Change `spell_correction.provider` in the config file to a different value, restart the service, and verify via a corrected request that the new corrector is active. No code file was modified.

**Acceptance Scenarios**:

1. **Given** `spell_correction.provider` is set to `"symspell"` in config, **When** the service starts, **Then** the SymSpell-based corrector is active.
2. **Given** `spell_correction.provider` is changed to a different registered value, **When** the service restarts, **Then** the new corrector is active without any code change.

---

### Edge Cases

- What happens when the input is a TikTok URL with no supplementary text? The URL should pass through correction without being corrupted (corrector must skip URLs or non-text tokens).
- What happens when the corrector dictionary does not recognise a term (a new restaurant name, a proper noun, a foreign word)? The term must be preserved exactly.
- What happens when input is in a non-English language? This iteration always uses `"en"` — non-English text passes through the English corrector, which will either leave it unchanged (unrecognised terms preserved) or apply English-context corrections. Full locale support is deferred.
- What happens when correction adds latency exceeding the endpoint's time budget? Correction must complete well within 1ms per word (per ADR-032 benchmark: 0.033ms/word at edit distance 2 for SymSpell), so the total budget impact is negligible for typical query lengths.
- What happens when the corrector raises an unhandled exception? The system logs the error and falls back to the raw uncorrected input — the request never fails due to a correction error.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST silently correct spelling in the user's input before any parsing, embedding, or LLM call in all three endpoints: extract-place, consult, and recall.
- **FR-002**: The system MUST use a swappable spell correction provider configured via a single value in the application configuration file. Swapping providers MUST require only a configuration change, not a code change.
- **FR-003**: The corrected text — not the raw input — MUST be what the extraction LLM and embedding pipeline operate on. For extract-place, correction improves LLM extraction quality, which leads to a better Google Places match and therefore a higher-quality validated name stored in `places.place_name` (indirect effect — the corrected text is the input to the extraction chain, not stored verbatim). For consult, the corrected query is what reaches the intent parser. For recall, the corrected query is what gets embedded for vector search and passed to full-text search.
- **FR-004**: The correction language is always `"en"` (English) for this iteration. The corrector interface accepts a `language` parameter to keep the path open, but no DB lookup for user locale is performed. Locale-aware correction is deferred to a future feature.
- **FR-005**: When the corrector cannot improve a term (proper noun, unknown word, URL fragment), the system MUST preserve the original term unchanged.
- **FR-006**: When the spell corrector raises an exception or is misconfigured, the system MUST fall back to the raw uncorrected input and MUST NOT fail the request with an error response.
- **FR-007**: URLs detected in the input MUST be excluded from spell correction to prevent URL corruption.
- **FR-008**: The spell correction provider contract MUST be defined as a swappable protocol/interface, consistent with the project's protocol abstraction rule for all swappable dependencies.
- **FR-009**: The system MUST include at least one Bruno test request per endpoint that demonstrates correction of a typo-laden input and confirms the corrected value appears in the stored record.

### Key Entities

- **SpellCorrector**: The swappable correction interface. Accepts a text string and a language code, returns the corrected string. Implementations wrap specific correction libraries. The active implementation is selected at startup from configuration.
- **CorrectionResult**: The output of a correction pass — the corrected text string (may be identical to input if no corrections were made).
- **LanguageCode**: A locale/language identifier (e.g., `"en"`, `"th"`) used to select the appropriate dictionary. Sourced from the user's stored locale or defaulted to `"en"`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A place submitted with a common English typo (edit distance 1 or 2) is stored with the corrected name 100% of the time, verifiable by direct database inspection.
- **SC-002**: Swapping the active spell correction provider requires changes to exactly one configuration value and zero application code files.
- **SC-003**: Spell correction adds no measurable latency to any endpoint for inputs under 50 words (correction completes in under 2ms total for typical query lengths).
- **SC-004**: All three endpoints (extract-place, consult, recall) handle typo-laden inputs and return a valid response — correction never causes a request to fail with a 4xx or 5xx error.
- **SC-005**: For a typo-input extraction, the Google Places-validated name stored as `place_name` is a recognisable, correctly-spelled place name — not the raw typo — confirmed via Bruno test request and database record inspection. (The corrected text feeds the LLM extractor; the stored name comes from Google Places validation on that corrected extraction.)

## Assumptions

- This iteration always uses English (`"en"`) for correction. No DB lookup for user locale is performed. The corrector interface accepts a `language` parameter so locale-aware correction can be wired in a future iteration without changing the Protocol or service signatures.
- The initial corrector implementation covers English only. Other languages are addressed by adding new implementations and dictionaries — no changes to the core pipeline are required.
- Correction is applied to the free-text portion of extract-place inputs only. TikTok URL inputs pass the URL through uncorrected; only the supplementary text (if any) is corrected.
- The spell correction library (`symspellpy`) will be added to the project's dependency manifest. No other infrastructure changes are needed.
- "Correction fires before any parsing, embedding, or LLM call" means the service layer applies correction as its first step, before dispatching to extractors, intent parsers, or embedding providers.

## Clarifications

### Session 2026-03-31

- Q: For extract-place, does "stored as places.place_name" mean the corrected user text is stored verbatim, or that correction feeds the LLM extractor which leads to a better Google Places match? → A: Correction feeds the LLM extractor (indirect effect); stored name comes from Google Places validation on the corrected extraction output.
- Q: Does this iteration implement DB-resident user locale lookup for correction language, or always use English? → A: Always use English (`"en"`) for this iteration; locale lookup is deferred to a future feature.

## Out of Scope

- Frontend spell correction or UI-level typo highlighting — correction is invisible to users and happens server-side only.
- NestJS-level correction — NestJS is an auth and routing layer only (per ADR-032).
- Correcting place names that are already stored in the database (retroactive correction).
- Multi-language dictionaries and user locale lookup — always English for this iteration.
- User-visible correction confirmation or "did you mean?" UI flows.
