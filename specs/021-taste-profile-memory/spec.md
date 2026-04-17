# Feature Specification: Taste Profile & Memory Redesign

**Feature Branch**: `021-taste-profile-memory`  
**Created**: 2026-04-17  
**Status**: Draft  
**Input**: User description: "Replace EMA-based taste model with signal_counts aggregation and LLM-generated taste_profile_summary. Delete RankingService. Simplify interactions table."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Taste profile builds from saved places and feedback (Priority: P1)

A user saves several places over time (restaurants, cafes, bars). Each save, recommendation acceptance, or rejection is recorded as an interaction. After enough interactions accumulate, the system automatically generates two artifacts from a single LLM call: a human-readable taste profile summary describing the user's preferences (top cuisines, price comfort, preferred ambiance, location patterns, rejections), and a set of taste chips — short UI-ready labels (e.g., "Izakaya lover", "Budget-friendly") each grounded in a specific signal_counts path and value.

**Why this priority**: The taste profile is the core personalization artifact. Without it, the system cannot personalize recommendations. Every other story depends on interactions being logged and aggregated correctly. Chips give the UI a way to display taste at a glance without parsing the summary.

**Independent Test**: Save 5+ places with varied attributes (different cuisines, price hints, subcategories). Verify that an interaction row is created for each save, signal counts are aggregated correctly, a taste profile summary is generated describing the user's patterns, and chips are generated with labels grounded in signal_counts.

**Acceptance Scenarios**:

1. **Given** a user with no prior interactions, **When** they save 3 places with cuisine="Japanese", **Then** an interaction row is created for each save, signal_counts shows `subcategory` and `attributes.cuisine` counts reflecting the 3 Japanese places, a taste_profile_summary is generated mentioning Japanese cuisine with "[3 signals]", and chips include a label referencing the cuisine with its signal count.
2. **Given** a user with 8 existing interactions, **When** they accept a recommendation for a place, **Then** a new interaction row of type "accepted" is created, signal_counts are re-aggregated from all interactions, and both taste_profile_summary and chips are regenerated with updated counts.
3. **Given** a user with 2 interactions (below the minimum threshold of 3), **When** they save a place, **Then** an interaction row is created but no taste_profile_summary or chips are generated (summary generation is skipped).

---

### User Story 2 - Debounced regeneration prevents redundant work (Priority: P2)

When a user saves multiple places in rapid succession (e.g., sharing a batch of TikTok videos), the system debounces taste profile regeneration so only one regeneration runs after the burst of activity settles, rather than one per save.

**Why this priority**: Without debouncing, a batch save of 10 places would trigger 10 LLM calls for summary generation. This wastes tokens and creates unnecessary load. The debounce mechanism is essential for production efficiency.

**Independent Test**: Trigger 5 saves within 10 seconds for the same user. Verify only one regeneration runs (after the debounce window expires), not five.

**Acceptance Scenarios**:

1. **Given** a debounce window of 30 seconds, **When** a user saves 5 places within 10 seconds, **Then** only one taste profile regeneration runs (approximately 30 seconds after the last save), and signal_counts reflect all 5 saves.
2. **Given** a pending debounce timer for a user, **When** the application shuts down, **Then** all in-flight debounce tasks are cancelled cleanly without errors.
3. **Given** two application instances handling requests for the same user, **When** both schedule regeneration, **Then** the regeneration is idempotent — running twice produces the same result with no data corruption (last-write-wins via full overwrite).

---

### User Story 3 - Onboarding signals feed the taste profile (Priority: P2)

During onboarding, the user is shown place "chips" to confirm or dismiss. Each confirmation or dismissal is recorded as an interaction and contributes to the taste profile — confirmations as positive signals, dismissals as negative signals (counted under rejections).

**Why this priority**: Onboarding is the fastest path to a useful taste profile for new users. Without onboarding signals flowing into the taste model, early personalization is impossible.

**Independent Test**: Simulate an onboarding flow where the user confirms 3 place chips and dismisses 2. Verify interaction rows are created with correct types (onboarding_confirm vs. onboarding_dismiss) and signal_counts reflect confirmations in the main tree and dismissals in the rejected branch.

**Acceptance Scenarios**:

1. **Given** a new user in onboarding, **When** they confirm a place chip, **Then** an interaction of type "onboarding_confirm" is created, and the place contributes to positive signal counts (subcategory, attributes).
2. **Given** a new user in onboarding, **When** they dismiss a place chip, **Then** an interaction of type "onboarding_dismiss" is created, and the place contributes to the rejected signal counts.

---

### User Story 4 - Consult returns candidates without numeric ranking (Priority: P3)

When a user asks for a recommendation (consult), the system returns enriched candidates in source order (saved places first, then discovered places) without applying a numeric ranking score. The agent (future work) will handle ranking using the taste profile summary and signal counts.

**Why this priority**: This is a transitional state — the current numeric RankingService is being deleted because it depends on the EMA taste vector which no longer exists. Returning unranked candidates is acceptable until the agent is built.

**Independent Test**: Issue a consult query for a user with saved places. Verify that candidates are returned with saved places listed before discovered places, and no numeric score is attached.

**Acceptance Scenarios**:

1. **Given** a user with saved places matching a query, **When** they issue a consult request, **Then** the response contains enriched candidates ordered by source (saved first, discovered second) with no numeric ranking score.
2. **Given** the RankingService has been deleted, **When** the consult pipeline runs, **Then** no errors occur related to missing ranking logic, and the response is well-formed.

---

### Edge Cases

- What happens when a user has interactions but all referenced places have been deleted? The aggregation skips rows with no joinable place data — no error, just fewer counts.
- What happens when the LLM generates a response that doesn't parse as valid structured output? The system retries once. If the second attempt also fails to parse, regeneration is skipped entirely — the next interaction signal will trigger another attempt.
- What happens when signal_counts aggregation produces zero counts across all categories? The system skips summary generation (falls under the min_signals guard).
- What happens when regeneration fails mid-way (e.g., LLM timeout)? The existing taste_profile_summary and chips are preserved (no partial update), and the failure is logged via Langfuse.
- What happens when chips reference a signal_counts path or value that doesn't exist? Each chip is validated against signal_counts after generation. Chips with an invalid source_field path or mismatched source_value are silently dropped. If more than half are dropped, no retry — surviving chips are written as-is.
- What happens when all generated chips are invalid? Zero chips are written. The summary is still persisted. This is logged as a warning via Langfuse metadata.
- What happens when the same place is saved twice (duplicate)? The save pipeline already handles duplicates via DuplicatePlaceError (ADR-054). A duplicate save does not create an interaction row.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST record every user interaction (save, accepted, rejected, onboarding_confirm, onboarding_dismiss) as an append-only row in the interactions table with the user ID, interaction type, and place ID.
- **FR-002**: System MUST aggregate all interactions for a user into a structured signal_counts object containing: total counts by type, counts by place_type, counts by subcategory (grouped by place_type), counts by source (saves only), counts by tag, counts by attribute (cuisine, price_hint, ambiance, dietary, good_for, location_context), and rejected counts as a separate branch.
- **FR-003**: System MUST generate two artifacts from a single LLM call: (a) a taste_profile_summary as a structured list of 3-6 lines, each with display text, a signal_count, and a source_field/source_value grounding it in signal_counts, and (b) a list of taste chips (3-8 short UI labels, 2-4 words each) each grounded in a specific signal_counts path and value. Both artifacts share the same grounding schema (source_field, source_value, signal_count).
- **FR-004**: System MUST skip taste_profile_summary generation when the user has fewer than a configurable minimum number of interactions (default: 3).
- **FR-005**: System MUST debounce taste profile regeneration per user so that rapid successive interactions trigger only one regeneration after a configurable delay window (default: 30 seconds).
- **FR-006**: System MUST cancel all in-flight debounce tasks cleanly when the application shuts down.
- **FR-007**: System MUST persist signal_counts, taste_profile_summary, and chips together in a single upsert operation keyed by user ID, along with the generation timestamp and the count of interactions used.
- **FR-008**: System MUST skip regeneration when the number of interactions has not changed since the last generation (stale-summary guard using generated_from_log_count).
- **FR-009**: System MUST prefix each summary line with "Early signal:" when the user's total saves are below a configurable threshold (default: 10).
- **FR-010**: System MUST trace each regeneration as a Langfuse span with signal_counts as input, taste_profile_summary as output, and metadata including user_id, log_row_count, prior_log_count, and debounce_window.
- **FR-011**: System MUST return consult candidates in source order (saved first, then discovered) without applying any numeric ranking score.
- **FR-012**: System MUST delete all EMA-based taste model logic (8 dimensions, decay rates, blending, weighted Euclidean distance scoring).
- **FR-013**: System MUST delete the RankingService and all associated configuration (ranking weights, scoring formula).
- **FR-014**: System MUST migrate the existing interaction_log table to the new interactions table schema in a single database migration, preserving all existing interaction data and mapping onboarding_explicit rows to onboarding_confirm or onboarding_dismiss based on the context column.
- **FR-015**: The prompt template for taste_profile_summary generation MUST be stored in a dedicated file, not hardcoded in application code.
- **FR-016**: Signal_counts aggregation MUST be a pure function with no I/O — it receives interaction rows and returns a structured result.
- **FR-017**: Both summary lines and chips MUST be validated against signal_counts after generation using a single validation function. Any item whose source_field path does not exist in signal_counts, or whose source_value does not appear at that path, MUST be dropped before persistence.
- **FR-018**: Dropped items (summary lines or chips) MUST be logged via Langfuse metadata with the count and details of dropped items.
- **FR-019**: Chips MUST only include signals with a count of 3 or more — the LLM prompt enforces this, and validation confirms it.
- **FR-020**: The LLM call for artifact generation MUST use structured output (JSON mode) and parse into a validated schema. A parse failure retries once; a second failure skips regeneration entirely (no partial write).
- **FR-021**: Each chip label MUST be 1-30 characters and each chip MUST reference a source_field (path in signal_counts) and source_value (value at that path) for UI traceability.
- **FR-022**: System MUST provide a helper to format the structured summary back into bullet-point text for agent prompt injection (the agent sees the same readable format regardless of storage structure).

### Key Entities

- **Interaction**: An append-only record of a user action (save, accept, reject, onboarding confirm/dismiss) linked to a specific place. Replaces the former InteractionLog with a simplified schema (no gain, no context JSONB).
- **TasteModel**: Per-user record storing the aggregated signal_counts (structured JSON), taste_profile_summary (structured list of grounded lines), and chips (list of validated taste chips). All three are structured JSON. Replaces the former EMA-based parameters column. Keyed by user_id as primary key.
- **SignalCounts**: Structured aggregation of all user interactions, broken down by totals, place_type, subcategory, source, tags, attributes (cuisine, price_hint, ambiance, dietary, good_for, location_context), and rejections. Used as input to the LLM for summary and chip generation.
- **SummaryLine**: A single pattern observation (max 200 characters) grounded in signal_counts via source_field and source_value, with the associated signal_count. source_value is optional (null for aggregate claims like total saves). Shares the same grounding schema as Chip.
- **Chip**: A short UI-ready label (2-4 words, max 30 characters) grounded in a specific signal_counts path (source_field) and value (source_value), with the associated signal count. Used by the product UI to display taste at a glance.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every user interaction (save, accept, reject, onboarding) results in a persisted interaction record within the same request cycle — zero silent drops.
- **SC-002**: Taste profile regeneration completes within 5 seconds of the debounce window expiring, including signal_counts aggregation and LLM summary generation.
- **SC-003**: A batch of 10 rapid interactions for the same user triggers exactly 1 regeneration, not 10 — verified by Langfuse trace count.
- **SC-004**: Every persisted summary line and chip references a valid source_field path and source_value that exist in signal_counts — no hallucinated numbers. Both artifact types are validated by the same grounding function.
- **SC-005**: Application shutdown completes within 5 seconds with zero orphaned background tasks.
- **SC-006**: All existing interaction data survives the database migration with correct type mapping — zero data loss.
- **SC-007**: Consult endpoint returns valid responses without errors after RankingService deletion — no regressions in the consult pipeline.

## Assumptions

- The agent that will use taste_profile_summary and signal_counts for ranking is out of scope for this feature. This feature delivers the data layer; the agent consumes it later.
- The existing user_memories system is unchanged by this feature — memory and taste are separate concerns.
- Multi-process debounce overlap is handled by idempotent regeneration (full overwrite from fresh aggregation), not by distributed locking.
- The PersonalFactsExtracted event and its handler are unchanged — they flow to UserMemoryService, not TasteModelService.
- Existing ConsultLog table and its repository are unchanged.
