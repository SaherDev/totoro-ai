# Feature Specification: LLM NER Enricher Redesign

**Feature Branch**: `014-ner-enricher-redesign`  
**Created**: 2026-04-08  
**Status**: Draft  
**Input**: Redesign LLMNEREnricher to pass full metadata context to GPT-4o-mini and return fully structured place candidates with no post-processing cleanup

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Full Metadata Extraction from Social URLs (Priority: P1)

When a user shares a TikTok, Instagram, or other social video URL, upstream enrichers populate the extraction context with a caption, hashtags, location tag, platform, and title. The NER enricher should pass all of this rich metadata to the LLM in a single structured call — not just the raw text — so the model has full context to extract accurate venue names with city, cuisine, price range, and place type.

**Why this priority**: This is the primary input path. Richer context means fewer hallucinated cities and more accurate venue type/price classification, directly improving recommendation quality downstream.

**Independent Test**: Can be tested by providing an `ExtractionContext` with `caption`, `hashtags`, `location_tag`, `platform`, and `title` set, mocking the LLM, and asserting that the full metadata block is sent and candidates are populated with all structured fields.

**Acceptance Scenarios**:

1. **Given** an `ExtractionContext` with `caption="Dinner at Le Bernardin"`, `hashtags=["#nyc", "#finedining"]`, `location_tag="New York"`, `platform="tiktok"`, `title="Best restaurant in NYC"`, **When** the enricher runs, **Then** the LLM receives a `<metadata>` block containing all five fields and returns structured candidates with `name`, `city`, `cuisine`, `price_range`, and `place_type`.

2. **Given** the LLM returns a candidate with `price_range="high"` and `place_type="restaurant"`, **When** the enricher appends to `context.candidates`, **Then** each `CandidatePlace` carries those fields at `source=ExtractionLevel.LLM_NER`.

---

### User Story 2 - Plain Text Extraction Without URL (Priority: P2)

When a user types a place name or description directly (no URL), the enricher should still run and extract venues from `supplementary_text`, passing whatever metadata is available (most fields will be `None` or empty).

**Why this priority**: Plain-text input is a supported path. The enricher must not silently skip it — returning no candidates when the user typed a venue name would break the extraction pipeline for this path.

**Independent Test**: Can be tested by providing an `ExtractionContext` with `supplementary_text="I love Nobu Tokyo"` and no URL or caption, asserting that the LLM is called and candidates are populated.

**Acceptance Scenarios**:

1. **Given** an `ExtractionContext` with `supplementary_text="I love Nobu Tokyo"` and `caption=None` and `url=None`, **When** the enricher runs, **Then** the LLM is called with a `<metadata>` block where `caption` contains the supplementary text and other fields default to `None`/empty, and `context.candidates` gains at least one entry.

2. **Given** an `ExtractionContext` where `supplementary_text` is populated but `caption` is not, **When** field resolution runs, **Then** `text_to_use = supplementary_text`, `platform = "unknown"`, `hashtags = []`.

---

### User Story 3 - Skip When No Text Is Available (Priority: P3)

When a URL was provided but all upstream caption enrichers failed (oEmbed timeout, yt-dlp error), the context has no caption and no supplementary text. The NER enricher should skip immediately — there is nothing to extract.

**Why this priority**: A no-op skip is safer and cheaper than sending a blank LLM call. This guard prevents unnecessary API cost and avoids hallucinated venues from empty prompts.

**Independent Test**: Can be tested by providing an `ExtractionContext` with `caption=None`, `supplementary_text=""`, asserting that the LLM is never called and `context.candidates` remains unchanged.

**Acceptance Scenarios**:

1. **Given** an `ExtractionContext` with `caption=None` and `supplementary_text=""`, **When** the enricher runs, **Then** no LLM call is made and `context.candidates` is unchanged.

2. **Given** an `ExtractionContext` with `caption=None` and `supplementary_text=None`, **When** the enricher runs, **Then** the enricher returns immediately without error.

---

### Edge Cases

- What happens when the LLM returns an empty `places` list? No candidates are appended; existing candidates are unchanged.
- What happens when the LLM call throws an exception? The error is logged as a warning, candidates are unchanged, and no exception propagates to the caller.
- What if `hashtags` contains mall or shopping center names (e.g., `#siamparagon`)? The prompt instructs the LLM not to treat these as city names.
- What if a hashtag is a typo of a city name (e.g., `#bangok`)? The prompt instructs the LLM to treat this as a contextual clue for Bangkok.
- What if `location_tag` and a hashtag disagree on the city? The LLM resolves this; no code-level override is applied.

## Clarifications

### Session 2026-04-08

- Q: Are upstream enrichers (yt-dlp, oEmbed) updated in this task to populate the new `ExtractionContext` fields (`platform`, `title`, `hashtags`, `location_tag`)? → A: Yes — upstream population is in scope for this task.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The enricher MUST skip (return immediately) when both `context.caption` and `context.supplementary_text` are absent or empty.
- **FR-002**: The enricher MUST use `context.caption` if set; otherwise fall back to `context.supplementary_text` as `text_to_use`.
- **FR-003**: The enricher MUST resolve `platform`, `title`, `hashtags`, and `location_tag` from `ExtractionContext` fields before building the prompt, defaulting to `"unknown"`, `None`, `[]`, and `None` respectively when absent.
- **FR-004**: The enricher MUST send all resolved fields to the LLM inside a `<metadata>` block in the user message, not inline in the system prompt.
- **FR-005**: The system prompt MUST include a defensive instruction (per ADR-044) telling the LLM to ignore any instructions appearing inside the `<metadata>` block.
- **FR-006**: The LLM response schema (`NERPlace`) MUST include `name`, `city`, `cuisine`, `price_range`, and `place_type` fields.
- **FR-007**: The enricher MUST append one `CandidatePlace` per extracted venue to `context.candidates` with `source=ExtractionLevel.LLM_NER`.
- **FR-008**: The enricher MUST NOT apply any post-processing to LLM-returned fields (no blocklist, no allowlist, no fuzzy matching, no street name filter).
- **FR-009**: The enricher MUST attach a Langfuse generation span on every LLM call (per ADR-025).
- **FR-010**: `ExtractionContext` MUST expose `platform`, `title`, `hashtags`, and `location_tag` fields for the enricher to read; if they don't exist today they must be added.
- **FR-011**: `CandidatePlace` MUST expose `price_range` and `place_type` fields; if they don't exist today they must be added.
- **FR-012**: `YtDlpMetadataEnricher` MUST populate the new `ExtractionContext` fields from the yt-dlp JSON response: `title` from `data["title"]`, `hashtags` from `data.get("tags", [])`, `platform` from `data.get("extractor", "unknown")`, `location_tag` from `data.get("location")`. These are set alongside the existing `description` → `caption` write. All fields are first-write-wins.
- **FR-013**: `TikTokOEmbedEnricher` MUST set `context.platform = "tiktok"` when successfully fetching the oEmbed response. Hashtags and location_tag are not available from oEmbed and are left for yt-dlp or other enrichers.

### Key Entities

- **ExtractionContext**: Shared mutable state threaded through all enrichers. Needs `platform`, `title`, `hashtags`, `location_tag` fields added. `YtDlpMetadataEnricher` is the primary populator of these fields; `TikTokOEmbedEnricher` sets `platform` only.
- **CandidatePlace**: Unvalidated place candidate produced by an enricher. Needs `price_range` and `place_type` fields added.
- **NERPlace / NERResponse**: Pydantic schemas for LLM output. Private to `llm_ner.py`. `NERPlace` has five fields: `name`, `city`, `cuisine`, `price_range`, `place_type`.
- **LLMNEREnricher**: The enricher class. Accepts an `InstructorClient` at construction. Exposes a single `async def enrich(context: ExtractionContext) -> None` method.
- **YtDlpMetadataEnricher**: Updated to also extract `title`, `hashtags`, `platform`, `location_tag` from the yt-dlp JSON response alongside the existing `description` → `caption` write.
- **TikTokOEmbedEnricher**: Updated to set `context.platform = "tiktok"` on successful fetch.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All three input cases (no text, text only, URL + text) produce the correct behavior — skip, extract, or extract — as verified by automated tests.
- **SC-002**: Every LLM call includes all five metadata fields in the `<metadata>` block, confirmed by test assertions on mock call arguments.
- **SC-003**: Every extracted candidate carries `city`, `cuisine`, `price_range`, and `place_type` directly from the LLM response — no code-level mutation of those fields after the call.
- **SC-004**: The `llm_ner.py` file contains no blocklist, allowlist, fuzzy matching logic, or street name post-filter after the redesign, verified by code inspection and test.
- **SC-005**: All existing extraction pipeline tests continue to pass after `ExtractionContext` and `CandidatePlace` schema changes.
- **SC-006**: `ruff check` and `mypy` pass with zero errors on `llm_ner.py` after changes.
- **SC-007**: `YtDlpMetadataEnricher` populates `platform`, `title`, `hashtags`, and `location_tag` on `ExtractionContext` from the yt-dlp JSON response, verified by unit tests mocking the subprocess output.
- **SC-008**: `TikTokOEmbedEnricher` sets `context.platform = "tiktok"` on successful oEmbed fetch, verified by unit test.

## Assumptions

- `ExtractionContext.platform`, `.title`, `.hashtags`, and `.location_tag` do not currently exist on the dataclass. They will be added as optional fields with appropriate defaults (`None` for scalar fields, `[]` for `hashtags`).
- `CandidatePlace.price_range` and `.place_type` do not currently exist. They will be added as optional fields defaulting to `None`.
- `_city_filter.py` is deleted entirely. `emoji_regex.py` also removes its `CITY_BLOCKLIST` import and the blocklist guard in `_extract_city_hint()` — the length+alpha check is sufficient and city correctness moves to the LLM.
- The Langfuse integration uses `get_langfuse_client()` from `providers/tracing.py` (no `get_langfuse_handler()` exists).
- The Instructor client's async `extract()` call signature is unchanged; only the messages and response model change.
- Upstream enricher updates are limited to adding field writes — no changes to retry logic, circuit breaker, or error handling behaviour.
- yt-dlp `tags` field is a `list[str]` without `#` prefix. These are stored as-is in `context.hashtags` and formatted with `#` in the LLM prompt template.
- `context.platform` from yt-dlp `extractor` will be a string like `"TikTok"`, `"Instagram"`, or similar. No normalisation applied — passed as-is to the LLM.
