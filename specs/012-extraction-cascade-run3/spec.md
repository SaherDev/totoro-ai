# Feature Specification: Extraction Cascade Run 3 — Integration and Cleanup

**Feature Branch**: `012-extraction-cascade-run3`
**Created**: 2026-04-06
**Status**: Draft
**Input**: User description: "Extraction cascade Run 3: wire ExtractionPersistenceService, rewrite ExtractionService, migrate PlaceSaved to place_ids list, update API schema to multi-place provisional shape, cleanup dead code"

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Multiple Places Saved from a Single Share (Priority: P1)

A user shares a TikTok URL that mentions more than one restaurant. The system extracts all candidates, validates them against Google Places, and saves every validated place in a single operation — returning the full list of saved places in a single response.

**Why this priority**: The old pipeline could only save one place per request. Multi-place output is the core value of the cascade architecture and unlocks the TikTok food-creator use case where a single video covers a tasting itinerary.

**Independent Test**: Submit a TikTok URL known to contain two distinct restaurant mentions; confirm the response includes both places with their respective `place_id` values and `confidence` scores, and that both rows exist in the database.

**Acceptance Scenarios**:

1. **Given** a TikTok URL referencing two restaurants, **When** `POST /v1/extract-place` is called, **Then** the response contains `provisional: false`, `places` with two entries, and `extraction_status: "saved"`.
2. **Given** a URL where both candidates resolve to the same Google Place record (dedup), **When** the request is processed, **Then** only one entry appears in `places` and only one row is written to the database.
3. **Given** a URL where all candidates are already saved for this user, **When** the request is processed, **Then** `places` is empty and `extraction_status` is `"duplicate"`.

---

### User Story 2 — Provisional Response for Background Extraction (Priority: P1)

When fast inline enrichers find nothing, the system immediately returns a provisional acknowledgement while continuing to extract in the background using subtitle, audio, and frame analysis. The user's save intent is not lost.

**Why this priority**: Without this, a failed fast extraction returns an error. With it, the system can still surface a place after a short delay — a materially better user experience for difficult inputs.

**Independent Test**: Submit a URL where caption and yt-dlp extraction produce no candidates; confirm the response has `provisional: true` and `extraction_status: "processing"`, and that a background task is enqueued with the pending enricher levels listed.

**Acceptance Scenarios**:

1. **Given** a URL where no inline candidates pass validation, **When** `POST /v1/extract-place` is called, **Then** the response has `provisional: true`, `places: []`, `extraction_status: "processing"`, and `pending_levels` lists the background enricher names.
2. **Given** the background enrichers subsequently find a place, **When** they complete, **Then** the place is saved to the database and `PlaceSaved` is dispatched — no second HTTP call required.
3. **Given** background enrichers find nothing either, **When** they complete, **Then** a warning is logged and no database write occurs.

---

### User Story 3 — Taste Model Updated for All Saved Places as One Batch (Priority: P2)

When one or more places are saved in a single extraction run, the taste model receives a single batched signal covering all saved places — not N separate signals for N places.

**Why this priority**: The taste model's EMA formula assumes one signal per user interaction. Firing N signals for a single share would over-weight that interaction and distort the taste vector. Batching is an ADR-042 requirement.

**Independent Test**: Save two places in one extraction call; confirm `PlaceSaved` was dispatched exactly once with both `place_ids`, and that `interaction_count` incremented by 2.

**Acceptance Scenarios**:

1. **Given** two places are saved in a single extraction run, **When** `PlaceSaved` is dispatched, **Then** the event contains `place_ids` with both IDs and `interaction_count` increases by 2.
2. **Given** the embedding loop fails for one place, **When** `save_and_emit` completes, **Then** `PlaceSaved` was already dispatched before the embedding loop ran — the taste signal is not lost.

---

### User Story 4 — Dead Code Removed, Old Pipeline Deleted (Priority: P3)

The old 9-step linear pipeline (`ExtractionDispatcher`, `PlainTextExtractor`, `TikTokExtractor`, legacy `ExtractionResult`, `ExtractionSource`, `compute_confidence`) is deleted. The codebase has one extraction path.

**Why this priority**: Dead code is a maintenance tax. Removing it reduces confusion, lint surface area, and the risk that a future developer routes a new feature through the old path by mistake.

**Independent Test**: After the cleanup phase, confirm `grep -r "ExtractionDispatcher\|ExtractionSource\|compute_confidence\|PlainTextExtractor\|TikTokExtractor" src/ tests/` returns zero matches.

**Acceptance Scenarios**:

1. **Given** the cleanup phase is complete, **When** the full test suite is run, **Then** all tests pass with zero regressions.
2. **Given** `dispatcher.py`, `extractors/tiktok.py`, `extractors/plain_text.py`, and `result.py` are deleted, **When** mypy is run, **Then** no missing import errors appear in any remaining file.

---

### Edge Cases

- What happens when `save_and_emit` is called with an empty `results` list? — Return `[]`, dispatch no event, write nothing.
- What happens when embedding fails for one of N places? — Log a warning, continue. Other embeddings still write. `PlaceSaved` was already dispatched for all N.
- What happens when `raw_input` is empty or whitespace-only? — Raise `ValueError` before calling the pipeline.
- What happens when `ExtractionPipeline.run()` returns `ProvisionalResponse`? — `save_and_emit` is NOT called; route handler returns `provisional: true` shape immediately.
- What happens when every candidate in the batch is a duplicate? — `saved_place_ids` is empty, `PlaceSaved` is NOT dispatched, method returns `[]`, response has `extraction_status: "duplicate"`.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `PlaceSaved` event MUST carry `place_ids: list[str]` (replacing `place_id: str`); all consumers of this event MUST be updated atomically in the same commit.
- **FR-002**: `ExtractionPersistenceService.save_and_emit` MUST write all new places to the database BEFORE dispatching `PlaceSaved`, and dispatch `PlaceSaved` BEFORE starting the embedding loop — this ordering is invariant.
- **FR-003**: The embedding loop in `save_and_emit` MUST catch all exceptions and log a non-fatal warning per failure; it MUST NOT re-raise or prevent the method from returning.
- **FR-004**: `ExtractionService.run` MUST delegate extraction to `ExtractionPipeline.run()` and persistence to `ExtractionPersistenceService.save_and_emit()` — no direct DB writes, no direct event dispatches in the service itself.
- **FR-005**: `ExtractionPendingHandler` MUST use `ExtractionPersistenceService` for persistence; the `persistence: Any` stub MUST be replaced with the typed dependency.
- **FR-006**: `ExtractPlaceResponse` MUST carry `provisional: bool`, `places: list[SavedPlace]`, `pending_levels: list[str]`, `extraction_status: str`, and `source_url: str | None`; old single-place fields (`place_id`, `place`, `confidence`, `requires_confirmation`) MUST be deleted.
- **FR-007**: `get_event_dispatcher` in `deps.py` MUST register `ExtractionPendingHandler` under the `"extraction_pending"` key; the handler MUST share the same `ExtractionPersistenceService` instance as `ExtractionService` via FastAPI dependency injection.
- **FR-008**: `TasteModelService.handle_place_saved` MUST accept `place_ids: list[str]` and process the full batch as one EMA update, incrementing `interaction_count` by `len(place_ids)`.
- **FR-009**: After cleanup, `dispatcher.py`, `extractors/tiktok.py`, `extractors/plain_text.py`, and `result.py` MUST not exist; `ExtractionSource`, `compute_confidence`, and `InputExtractor` MUST not appear in `src/` or `tests/`.
- **FR-010**: All type annotations MUST pass `mypy --strict` after Phase 11 (before Phase 12 begins); type errors from the rewrite MUST be resolved before wiring.
- **FR-011**: The `ExtractionPending` dataclass MUST carry a comment explaining why it is intentionally a dataclass and not a `DomainEvent` subclass — the `cast(DomainEvent, event)` workaround is intentional and must be visible to future readers.

### Key Entities

- **PlaceSaved** (event): Domain event; carries `place_ids: list[str]` and `place_metadata: dict`; dispatched after all DB writes succeed, before embedding loop.
- **ExtractionPersistenceService**: Shared write-path service; dedup check → Place write → PlaceSaved dispatch → embedding loop; used by both inline and background execution paths.
- **ExtractionService**: Thin orchestrator; delegates to `ExtractionPipeline` and `ExtractionPersistenceService`; returns `ExtractPlaceResponse`.
- **ExtractPlaceResponse** (API schema): Multi-place response shape with provisional flag and list of `SavedPlace` objects.
- **SavedPlace** (API schema): Per-place entry carrying `place_id`, `place_name`, `address`, `city`, `cuisine`, `confidence`, `resolved_by`, `external_provider`, `external_id`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `POST /v1/extract-place` with a multi-mention TikTok URL returns all validated places in a single response; no partial saves (all validated candidates saved or none).
- **SC-002**: `POST /v1/extract-place` with a URL that produces no inline candidates returns `provisional: true` without blocking the HTTP response.
- **SC-003**: `PlaceSaved` is dispatched at most once per extraction run regardless of how many places are saved; taste model `interaction_count` increments by exactly `len(place_ids)`.
- **SC-004**: Embedding failure for one place in a multi-place save does not prevent remaining embeddings from being written and does not cause an HTTP error response.
- **SC-005**: `poetry run pytest && poetry run ruff check src/ tests/ && poetry run mypy src/` all pass with zero failures after Phase 13 cleanup.
- **SC-006**: No file in `src/` or `tests/` imports any deleted symbol after Phase 13; verified by grep returning zero matches.

## Assumptions

- NestJS must be updated to read the new `ExtractPlaceResponse` shape before production deployment — this is a breaking contract change that must be coordinated.
- `get_by_provider(external_provider, external_id)` returns the existing `Place` or `None`; dedup key is `(external_provider, external_id)`, not user-scoped.
- `ExtractionPipeline` from Run 2 is fully functional and its contract does not change in this run.
- Background enrichers (`SubtitleCheckEnricher`, `WhisperAudioEnricher`, `VisionFramesEnricher`) constructors are already defined from Run 2 and instantiatable at wiring time.
- `parse_input(raw_input)` exists and separates a URL from supplementary text; if absent, a minimal implementation extracting the first URL-shaped token is sufficient for this run.

## Dependencies and Risks

- **Breaking API contract**: `ExtractPlaceResponse` shape change requires coordinated NestJS update before production deploy; do not deploy Phase 12 until NestJS is updated.
- **Shared persistence instance**: `ExtractionPersistenceService` must share the same DB session across `ExtractionService` and `ExtractionPendingHandler`; a second instance with a separate session breaks transactional isolation.
- **Ordering invariant**: `PlaceSaved` dispatch before embedding loop is load-bearing for the taste model; any refactor must preserve this order.
- **mypy gate before Phase 12**: Phase 12 wiring must not begin until Phase 11 passes mypy; the type boundary between new cascade types and old schemas is the highest-risk surface.
