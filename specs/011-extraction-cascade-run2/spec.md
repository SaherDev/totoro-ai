# Feature Specification: Extraction Cascade Run 2

**Feature Branch**: `011-extraction-cascade-run2`
**Created**: 2026-04-06
**Status**: Draft
**Input**: User description: "Extraction cascade Run 2 — Phases 5–7: GooglePlacesValidator, dedup/EnrichmentPipeline, background enrichers (subtitle, audio, vision), ExtractionPipeline three-phase runner, ExtractionPendingHandler."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Immediate Place Identification from Shared Content (Priority: P1)

A user shares a social media URL (TikTok, Instagram, etc.) containing a restaurant mention. The system identifies and validates the place immediately from inline signals (captions, metadata, emojis) by checking all candidate names against an authoritative places registry in parallel and returning a confident match.

**Why this priority**: This is the primary happy path — most URLs will have enough inline signal. Delivering an immediate, validated result is the core value proposition of the extraction system.

**Independent Test**: Submit a URL whose caption clearly names a restaurant. The system returns a validated place with a confidence score above threshold without triggering background processing.

**Acceptance Scenarios**:

1. **Given** a URL whose caption contains one or more place names, **When** the extraction pipeline runs, **Then** all candidate names are validated against the places registry in parallel and the validated results are returned immediately.
2. **Given** multiple candidate places extracted from the same URL, **When** two candidates share the same name (found by two different signals), **Then** the duplicate is collapsed into one result marked as corroborated, increasing its confidence.
3. **Given** a candidate that cannot be matched in the places registry, **When** validation runs, **Then** that candidate is excluded from results rather than returned with low confidence.

---

### User Story 2 - Deferred Place Identification via Background Enrichment (Priority: P2)

A user shares a URL where inline signals (caption, metadata) are insufficient to identify the place. The system acknowledges the request immediately with a "still processing" status, then continues extraction in the background using audio transcription and video frame analysis, eventually delivering validated results.

**Why this priority**: Without this, any URL with sparse captions silently fails. The background pipeline turns a hard failure into a deferred success, covering a significant share of real-world URLs.

**Independent Test**: Submit a URL with no caption text. The system returns a provisional "processing" response and, after background enrichment completes, produces a validated place result (verified via the persistence save pathway).

**Acceptance Scenarios**:

1. **Given** a URL with no inline candidates after enrichment, **When** the pipeline completes inline phases and validation finds nothing, **Then** the system immediately returns a provisional response indicating processing is ongoing.
2. **Given** a provisional response has been issued, **When** background enrichers run (subtitle extraction, audio transcription, vision frame analysis), **Then** any identified candidates are validated and saved.
3. **Given** background enrichment also finds nothing, **When** the handler completes, **Then** a warning is logged and no result is persisted — no unhandled error occurs.

---

### User Story 3 - Subtitle-Assisted Place Identification (Priority: P2)

When a video URL has available subtitles or auto-generated captions, the system uses those subtitles as a high-fidelity text source to identify place names before falling back to audio transcription or visual analysis.

**Why this priority**: Subtitles are more accurate than audio transcription and cheaper than vision analysis. Prioritising them reduces cost and latency for the majority of URLs that have subtitles available.

**Independent Test**: Submit a URL whose video has downloadable subtitles but no useful caption metadata. Verify the subtitle text is used to produce place candidates, and that audio transcription is skipped.

**Acceptance Scenarios**:

1. **Given** a video URL with available subtitles, **When** the background enricher runs, **Then** subtitle text is extracted, place names are identified from it, and audio transcription is skipped.
2. **Given** no subtitles are available, **When** the subtitle enricher runs, **Then** it completes without error and audio transcription proceeds.

---

### User Story 4 - Audio Transcription Fallback (Priority: P3)

When subtitles are unavailable, the system transcribes the video's audio track to extract spoken place mentions, using a two-tier approach that first attempts a CDN URL pass-through before falling back to downloading the audio stream.

**Why this priority**: Audio transcription is the next-best signal after subtitles but has higher latency and cost. It serves as the safety net for content where the place is spoken but not shown as text.

**Independent Test**: Submit a URL with no subtitles where the speaker mentions a restaurant. Verify transcription produces the place name as a candidate and validates it.

**Acceptance Scenarios**:

1. **Given** a URL with no subtitles, **When** audio transcription runs, **Then** the audio is transcribed and place names are extracted from the transcript.
2. **Given** transcription exceeds 8 seconds, **When** the timeout fires, **Then** the enricher logs a warning and returns without raising an error, allowing the pipeline to continue.

---

### User Story 5 - Visual Frame Analysis Fallback (Priority: P3)

When neither subtitles nor audio yield place candidates, the system analyses video frames (specifically the bottom third of the screen where on-screen text overlays typically appear) to identify place names visually.

**Why this priority**: Video content frequently shows on-screen location tags or restaurant signage. Vision analysis is the last-resort enricher before extraction gives up.

**Independent Test**: Submit a URL where the place name appears as a text overlay in the video but is not in captions or audio. Verify vision analysis produces a candidate and validates it.

**Acceptance Scenarios**:

1. **Given** a URL with on-screen text showing a place name, **When** vision frame analysis runs, **Then** up to 5 frames are analysed and the place name is extracted as a candidate.
2. **Given** frame analysis exceeds 10 seconds, **When** the timeout fires, **Then** the enricher logs a warning and returns without raising an error.

---

### Edge Cases

- What happens when all candidates from a URL fail Places validation? → Validator returns nothing; pipeline falls through to background processing or provisional response.
- What happens when two candidates have the same name but come from different signal levels (e.g., emoji regex + LLM NER)? → They are collapsed into one corroborated candidate with the higher-priority (lower-index) source level retained.
- What happens when the Places registry call throws an error for one candidate but succeeds for others? → That candidate is treated as not found; other candidates still complete and are returned.
- What happens when `url` is None (plain text input)? → All URL-dependent enrichers (subtitle, audio, vision) skip gracefully; only text-based enrichers run.
- What happens when background enrichment finds nothing after all three enrichers? → Warning is logged, no result is saved, no exception is raised.
- What happens when the same candidate name appears at the same extraction level? → The first occurrence wins; the result is marked corroborated.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST validate all extracted place candidates against an authoritative places registry in parallel, not sequentially, so validation time is bounded by the slowest single lookup.
- **FR-002**: The system MUST exclude any candidate that cannot be matched in the places registry (no external identity) or whose calculated confidence is zero.
- **FR-003**: The system MUST deduplicate candidates that share the same normalised name, retaining the highest-priority source and marking the winner as corroborated.
- **FR-004**: The system MUST return a validated result immediately when inline enrichment produces at least one valid candidate.
- **FR-005**: The system MUST return a provisional "processing" response when no inline candidates are validated, and dispatch a background processing event carrying all context needed to continue.
- **FR-006**: The background handler MUST run subtitle extraction, audio transcription, and vision frame analysis in sequence, deduplicate, validate, and persist any results found.
- **FR-007**: The background handler MUST log a warning and exit cleanly when no results are found after all background enrichers complete — no exception may propagate.
- **FR-008**: Each background enricher MUST skip gracefully when its required input (URL or prior transcript) is absent.
- **FR-009**: Audio transcription MUST enforce an 8-second hard timeout; vision frame analysis MUST enforce a 10-second hard timeout — timeout expiry must not raise an unhandled exception.
- **FR-010**: Confidence scoring MUST incorporate the source signal level, match quality from the places registry, corroboration status, and a configurable maximum cap — none of these values may be hardcoded.
- **FR-011**: The places validator MUST be swappable via an interface contract so alternative registry providers can be substituted without changing pipeline code.
- **FR-012**: The audio transcription provider MUST be swappable via an interface contract so alternative transcription services can be substituted without changing enricher code.
- **FR-013**: A single failed places lookup among multiple candidates MUST NOT prevent the remaining candidates from being processed and returned.

### Key Entities

- **CandidatePlace**: A potential place identified from a single signal source — carries name, city, cuisine, source level, and corroboration flag.
- **ExtractionResult**: A validated place with confirmed external identity, confidence score, and provenance — the final output of a successful extraction.
- **ExtractionContext**: The mutable working state for one extraction run — holds URL, user ID, accumulated candidates, transcript, and pending enrichment levels.
- **ProvisionalResponse**: The immediate response returned when background processing is required — carries status, confidence, and the list of pending enrichment levels.
- **ExtractionPending**: The domain event dispatched when inline extraction is insufficient — carries full context so the background handler can continue without restarting.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: URLs with clear inline place signals (caption, metadata, emoji) are fully validated and returned without triggering background processing — 100% of such inputs resolve via inline phases.
- **SC-002**: When multiple candidates are validated in parallel, all validation calls are issued concurrently — total validation time is bounded by the slowest single call, not their sum (verifiable by test).
- **SC-003**: A single failed places lookup among multiple candidates does not prevent the remaining candidates from being returned — partial-failure resilience is verifiable by automated test.
- **SC-004**: Background enrichment produces validated results for URLs where inline signals were absent — the end-to-end pipeline successfully identifies places from spoken or visually-presented location signals.
- **SC-005**: All enricher timeouts (audio 8 s, vision 10 s) are enforced and no enricher can block the background pipeline indefinitely — verifiable by test with mocked slow dependencies.
- **SC-006**: The deduplication function correctly collapses 100% of same-name candidates and marks winners as corroborated — verifiable by unit test with deterministic inputs.
- **SC-007**: The full automated test suite passes with zero regressions to existing pipeline behaviour after all new components are added.

## Assumptions

- Run 1 types (`ExtractionLevel`, `CandidatePlace`, `ExtractionContext`, `ExtractionResult`, `ProvisionalResponse`, `ExtractionPending`) and all five inline enrichers are already in place and passing tests.
- The existing Google Places client and match quality classifications are reused without modification.
- `ExtractionPersistenceService` does not yet exist and will be wired in Run 3 — the background handler's persistence dependency is a typed stub for now.
- The vision frame enricher uses the orchestrator model role as configured in app settings — no model name is hardcoded.
- All LLM calls attach the observability/tracing handler per project standards.
- Groq Whisper is the audio transcription provider for this run; the interface contract ensures this can be swapped in future runs.

## Out of Scope

- Persistence of validated results to the database (`ExtractionPersistenceService`) — deferred to Run 3.
- Wiring the `ExtractionPipeline` and `ExtractionPendingHandler` into the HTTP route layer — deferred to Run 3.
- Notification or callback to the product repo when background extraction completes — deferred to a later run.
- Modifying the existing extraction service, result model, extraction dispatcher, or any existing extractor.
