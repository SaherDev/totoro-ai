# Feature Specification: Onboarding Signal Tier

**Feature Branch**: `023-onboarding-signal-tier`
**Created**: 2026-04-18
**Status**: Draft
**Input**: User description: "Implement onboarding signal tier architecture — chip status lifecycle (pending/confirmed/rejected), signal_tier derivation (cold/warming/chip_selection/active), CHIP_CONFIRM signal handler, taste model regeneration with confirmed/rejected/pending sections, and agent behavior per tier."

## Clarifications

### Session 2026-04-18

- Q: Once a chip is confirmed or rejected, is that status permanent across all future rounds? → A: Confirmed is permanent; rejected may re-surface as pending in a later round if the underlying signal count keeps growing, giving the user another chance to confirm. chip_confirm never mutates a confirmed chip.
- Q: How should the warming-tier discovery/retrieval blend be specified? → A: Config-driven under the `taste_model` block with a default of 80% discovery / 20% retrieval, so it can be tuned from evaluations without code changes.
- Q: How should a duplicate chip_confirm submission be handled? → A: No deduplication. Every chip_confirm writes an interaction row and dispatches a rewrite event. The rewrite job is idempotent by construction (rebuilds summary from current state), so duplicate events are harmless redundant work.
- Q: Can a user in chip_selection tier bypass chip confirmation and still receive a recommendation? → A: No bypass. The product repo gates on `signal_tier` from `GET /v1/user/context` and renders the chip-selection UI directly; it does not call `/v1/consult` until `chip_confirm` resolves every pending chip. No skip signal, no soft fallback, no time-based auto-promotion.
- Q: Where does the onboarding / chip-selection message copy live? → A: This repo does not own copy. The product repo gates on `signal_tier` returned by `GET /v1/user/context` and decides whether to call `/v1/consult` at all. At `cold` and `chip_selection` tiers the frontend never calls `/v1/consult`; it renders the onboarding or chip-selection UI directly from the user-context response. No envelope discriminator is added to `/v1/consult` — consult is consult. (Revised 2026-04-18: earlier draft proposed an envelope discriminator, which contradicted the frontend-gates model; the envelope is dropped.)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - New user context reports cold tier so the product surfaces onboarding (Priority: P1)

A person who has never saved a place opens the app. The product repo calls `GET /v1/user/context`, which returns `signal_tier="cold"` with no chips and a zero saved-places count. The product UI uses that tier to render an onboarding screen directly — it does not call `/v1/consult` and does not send a consult chat request on the user's behalf.

**Why this priority**: Without a reliable cold signal exposed to the product, a brand-new user asking "where should I eat?" would receive a low-signal, generic recommendation that damages first impressions. Exposing the tier cleanly is the foundation — every other tier inherits the principle that product behavior matches signal maturity, and the product repo owns the user-facing rendering.

**Independent Test**: A test user with zero interactions calls `GET /v1/user/context`. The response carries `signal_tier="cold"`, `saved_places_count=0`, and `chips=[]`. No LLM call is made; no candidate pipeline is triggered.

**Acceptance Scenarios**:

1. **Given** a user has zero interactions recorded, **When** `GET /v1/user/context` is called, **Then** the response reports `signal_tier="cold"` and an empty chips array.
2. **Given** the product repo sees `signal_tier="cold"`, **When** it decides how to handle a consult-intent message, **Then** it renders its onboarding UI directly without calling `/v1/consult`.

---

### User Story 2 - User with a handful of saves receives discovery-leaning recommendations (Priority: P1)

A user has saved a few places but not yet enough to trigger chip selection. The assistant still runs the recommendation pipeline but leans heavily toward discovery (new places) rather than retrieving from the user's small saved set, since the saved set is not yet representative. The early taste summary is treated as a weak signal, not an authoritative profile.

**Why this priority**: This is the bridge tier between cold-start onboarding and personalized ranking. Without it, the system either fails to respond (cold behavior extended too far) or over-fits to two or three saves (active behavior triggered too early). Both produce bad recommendations at the most fragile point in the user journey.

**Independent Test**: A test user with a small number of saves (below the round_1 threshold) sends a consult query. The consult pipeline runs, returns candidates weighted toward discovery over retrieval, and the taste summary is used only as a weak influence on ranking.

**Acceptance Scenarios**:

1. **Given** a user has accumulated fewer signals than the round_1 threshold, **When** they consult, **Then** the assistant runs the consult pipeline with discovery weighted over retrieval.
2. **Given** a user is in the warming tier, **When** context is reported, **Then** the signal tier is "warming".

---

### User Story 3 - User explicitly confirms or rejects suggested taste chips (Priority: P1)

Once enough signals have been accumulated to surface candidate taste chips, the product sees `signal_tier="chip_selection"` on `GET /v1/user/context` and renders a chip-confirmation screen from the pending chips in that same response. The product does not call `/v1/consult` while the user is in this tier. When the user submits their choices via `POST /v1/signal` with `signal_type="chip_confirm"`, their confirmations and rejections lock into their taste profile.

**Why this priority**: Explicit user input resolves ambiguity that behavioral signals alone cannot. A user who has saved three ramen places might genuinely love ramen or might have been sharing them with a friend. Confirmation converts an inference into a fact and anchors all future recommendations.

**Independent Test**: A test user crosses the round_1 signal threshold. `GET /v1/user/context` reports `signal_tier="chip_selection"` with pending chips. The user submits a chip_confirm signal with mixed confirmed and rejected items. On re-reading context, every submitted chip reflects its new status and selection round, and no confirmed chip was downgraded.

**Acceptance Scenarios**:

1. **Given** a user has crossed the round_1 threshold and has pending chips, **When** `GET /v1/user/context` is called, **Then** the response reports `signal_tier="chip_selection"` and includes the pending chips so the product UI can render the chip-selection screen without a consult call.
2. **Given** a user submits a chip_confirm signal, **When** the system processes it, **Then** each referenced chip's status is updated to confirmed or rejected and the selection_round is recorded.
3. **Given** a chip already has a confirmed status, **When** a subsequent signal regeneration cycle runs, **Then** the chip's status and selection_round are preserved and not overwritten.
3a. **Given** a chip was previously rejected, **When** its underlying signal count grows and a later regeneration cycle runs, **Then** the chip may be reset to pending with a null selection_round so the user is re-offered the preference.
4. **Given** a user has confirmed all relevant chips and no pending chips remain, **When** the system reports their context, **Then** the signal tier becomes "active".

---

### User Story 4 - Taste profile summary reflects explicit preferences with appropriate confidence (Priority: P2)

As the user's profile matures from pure behavioral signals into a mix of confirmed, rejected, and pending items, the natural-language taste profile summary reflects that structure. Confirmed preferences read as assertive facts. Rejected preferences are stated as explicit dislikes. Still-pending behavioral patterns read as probabilistic observations with signal counts attached.

**Why this priority**: This powers downstream agent behavior. When the agent reasons about a candidate, it can trust confirmed preferences, respect explicit dislikes, and hedge on probabilistic patterns. Without these distinctions, the agent treats all signals the same and either over-commits to weak patterns or ignores strong ones.

**Independent Test**: A test user has a mix of confirmed, rejected, and pending chips. The regeneration job runs. The resulting taste_profile_summary contains sentences labeled appropriately — assertive for confirmed, explicit negative for rejected, probabilistic with signal counts for pending.

**Acceptance Scenarios**:

1. **Given** a user has no confirmed or rejected chips, **When** the taste summary regenerates, **Then** every sentence is a behavioral-signal observation with a signal count annotation.
2. **Given** a user has confirmed chips, **When** the taste summary regenerates, **Then** confirmed preferences appear as assertive positive sentences annotated with a confirmation marker.
3. **Given** a user has rejected chips, **When** the taste summary regenerates, **Then** rejected preferences appear as explicit negative sentences annotated with a rejection marker.
4. **Given** the regeneration job runs repeatedly, **When** it rewrites the summary, **Then** the entire summary is rewritten from scratch rather than appended to a prior version.

---

### User Story 5 - Active user receives fully personalized recommendations (Priority: P2)

Once the user has confirmed or rejected their taste chips and has no pending chips blocking the flow, every future consult runs the full personalization pipeline. Confirmed preferences positively influence ranking. Rejected preferences exclude candidates from the pool. Probabilistic pending patterns influence ranking more weakly than confirmed ones.

**Why this priority**: This is the steady-state experience. The three earlier tiers exist only to get the user here. Correct active-tier behavior is the long-term value of the whole tier system.

**Independent Test**: A test user in the active tier consults. The assistant runs the consult pipeline. Confirmed preferences are passed to the ranker as positive signals. Rejected items are filtered out of the candidate pool before scoring.

**Acceptance Scenarios**:

1. **Given** a user has confirmed chips and no pending chips, **When** they consult, **Then** the assistant runs the consult pipeline normally and confirmed items act as positive ranking signals.
2. **Given** a user has rejected chips, **When** they consult, **Then** candidates matching rejected preferences are excluded before scoring.

### Edge Cases

- What happens when a chip_confirm request references a source_field/source_value pair that is not present in the user's current chip list? The non-matching chip is ignored and the request still succeeds for the remaining valid matches.
- What happens when two chip_confirm requests arrive for the same round in rapid succession (e.g., network retry)? Both are written to the interaction log and both dispatch a rewrite event. On overlapping chips the second submission's status wins (subject to FR-006a — already-confirmed chips are untouched). The rewrite job is idempotent, so duplicate events produce the same summary, just with redundant work.
- What happens when a user's signal count briefly drops below round_1 after a rejection (e.g., after a REJECTED interaction)? The signal tier derivation always uses the highest stage the count currently satisfies; tiers can only move forward once round_1 has been reached, since confirmed chip statuses are locked.
- What happens when a chip the user previously rejected keeps accumulating signals? The regeneration job MAY reset it to pending and null out its selection_round so the user is re-offered the same preference in a later round. Confirmed chips never re-surface.
- How does the system handle a user whose regeneration job adds a new pending chip after they have already completed round_1? The new pending chip places the user back into the chip_selection tier until they confirm or reject it, preserving prior confirmations.
- What happens if the taste summary regeneration fails mid-run? The prior summary remains unchanged and the failure is logged. The next triggered regeneration cycle will attempt a fresh rewrite.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST record every taste chip with a structured shape that captures the label text, the current signal count, the source field and value that produced the chip, the current status (pending, confirmed, or rejected), and the selection round in which the status was set (null until set).
- **FR-002**: The system MUST expose a signal tier value to consumers (the user-context endpoint and the agent) that is derived from the user's current signal count and chip state, and is never persisted as a stored field.
- **FR-003**: The signal tier derivation MUST produce "cold" when the user has zero interactions, "warming" when the count is below the round_1 threshold, "chip_selection" when the count meets a selection-stage threshold and at least one chip is still pending, and "active" when the count meets a selection-stage threshold and no chips remain pending.
- **FR-004**: The system MUST provide configuration for the minimum signal count required for a chip to appear, the maximum number of chips that can exist at once, the named selection stages with their signal-count thresholds, and the warming-tier ranking blend expressed as a discovery/retrieval weight pair (default 80% discovery / 20% retrieval).
- **FR-005**: The regeneration job MUST add newly surfaced chips with status "pending" and no selection round once their source signal count crosses the chip threshold.
- **FR-006**: The regeneration job MUST update the signal count on existing chips without ever overwriting a confirmed status or clearing a confirmed chip's selection round. A previously rejected chip MAY be reset to status "pending" with a null selection round by the regeneration job if its signal count has grown since rejection, so the user can be offered the same preference in a later round.
- **FR-006a**: A chip_confirm submission MUST be idempotent with respect to already-confirmed chips — if a submitted chip matches an already-confirmed chip by source field and source value, that chip is left untouched regardless of the submitted status.
- **FR-007**: The user context endpoint MUST return the user identifier, the saved places count, the current signal tier, and the full structured chip array (not just labels). The endpoint MUST perform no LLM call.
- **FR-008**: The signal endpoint MUST accept a chip_confirm signal type whose payload identifies the selection round and the list of chips with their user-chosen statuses.
- **FR-009**: On receiving a chip_confirm signal, the system MUST write an interaction row of type "chip_confirm" with the full request metadata attached.
- **FR-010**: On receiving a chip_confirm signal, the system MUST merge each submitted chip into the stored chip array by matching on source field and source value, updating status and selection round on matched entries.
- **FR-011**: On receiving a chip_confirm signal, the system MUST dispatch a chip-confirmation domain event that triggers a background taste-profile rewrite.
- **FR-012**: The signal endpoint MUST return a successful response to chip_confirm requests without waiting for the taste profile rewrite to complete.
- **FR-012a**: The signal endpoint MUST NOT deduplicate chip_confirm submissions. Every submission writes its own interaction row and dispatches its own rewrite event. The rewrite handler MUST be idempotent with respect to repeat invocations on unchanged state — running it twice in succession produces the same taste profile summary as running it once.
- **FR-013**: The taste profile rewrite triggered by chip confirmation MUST build a prompt that includes four sections — behavioral signals, user-confirmed items, user-rejected items, and still-pending items — with any empty section explicitly represented as empty rather than omitted.
- **FR-014**: The taste profile rewrite MUST produce assertive positive sentences for confirmed items, explicit negative sentences for rejected items, and probabilistic sentences with signal counts for pending items. Negative statements MUST only be generated from rejected items, never inferred from low pending signal counts.
- **FR-015**: Confirmed and rejected sentences MUST be annotated with a confirmation or rejection marker; pending sentences MUST be annotated with a signal count marker.
- **FR-016**: Each regeneration cycle MUST rewrite the full taste profile summary from scratch rather than editing or appending to the prior version.
- **FR-017**: Before the user has any confirmed or rejected chips, the regeneration job MUST use a simpler prompt that contains only the behavioral-signals section. The behavioral-signals regeneration MUST trigger after every save, accepted, and rejected interaction.
- **FR-018**: After chip confirmation has occurred, subsequent regeneration cycles triggered by new behavioral interactions MUST use the four-section prompt, preserving confirmed and rejected items unchanged and reflecting any newly crossed pending chips in the pending section.
- **FR-019**: The `GET /v1/user/context` endpoint MUST be the single source of truth for the user's signal tier and currently-pending chips. The product repo reads this endpoint and gates all consult-intent traffic accordingly.
- **FR-020**: When the consult pipeline runs (warming or active tier only — the product repo never calls it at cold or chip_selection), the pipeline MUST apply a warming-tier discovery/saved candidate-count blend in the warming tier using the configured ratio (default 80/20), and run unchanged in the active tier. The service MUST NOT add a message-type discriminator to `ConsultResponse` or otherwise special-case cold/chip_selection traffic at the HTTP boundary — tier gating lives in the product repo.
- **FR-020a**: The chip_selection tier MUST be a hard gate in the product repo. There is no skip signal, no soft fallback to warming behavior after repeated attempts, and no time-based auto-promotion. A user leaves chip_selection only by submitting a chip_confirm that resolves (confirms or rejects) every pending chip, and the product repo stops calling `/v1/consult` for that user until the tier advances.
- **FR-021**: In the active tier, confirmed chips MUST be used as positive signals consumed by `ConsultService` (passed through `reasoning_steps` until the agent is built — ADR-058), and rejected chips MUST exclude matching candidates from the pool before scoring.
- **FR-022**: The interaction persistence layer MUST support attaching free-form structured metadata to any interaction row, and the interaction type enumeration MUST include a chip_confirm value.

### Key Entities *(include if feature involves data)*

- **Chip**: A candidate taste preference derived from behavioral signals. Holds the displayed label, the aggregated signal count that surfaced it, the source field and value that generated it, a lifecycle status (pending, confirmed, or rejected), and the selection round in which its status was set.
- **Interaction**: An append-only record of user actions that influence the taste profile. Each interaction has a type (save, accepted, rejected, chip_confirm) and may carry structured metadata — for chip_confirm, that metadata captures the round name and the full set of chip statuses submitted.
- **Taste Profile Summary**: A natural-language description of the user's preferences, rewritten from scratch on every regeneration cycle. Its structure reflects the mix of confirmed, rejected, and pending chips at the moment of regeneration.
- **Signal Tier**: A derived label (cold, warming, chip_selection, active) computed on demand from the user's signal count and chip state. Never stored. Consumed by the user-context response and the agent's state machine.
- **Chip Confirmation Event**: A domain event dispatched after a chip_confirm signal is processed. Triggers the background taste profile rewrite using the chip-status-aware prompt sections.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every new user's `GET /v1/user/context` response reports `signal_tier="cold"`; the product repo never calls `/v1/consult` while that tier is reported.
- **SC-002**: Between the first save and the round_1 threshold, every `/v1/consult` call runs the pipeline with the warming-tier discovery/saved candidate-count blend from config applied (default 80% discovery / 20% saved); saved results never dominate candidate mix before round_1.
- **SC-003**: When a user crosses the round_1 threshold, the next `GET /v1/user/context` response reports `signal_tier="chip_selection"` with pending chips populated, and the product repo stops calling `/v1/consult` for that user until chip_confirm resolves every pending chip.
- **SC-004**: Among users who have reached the active tier, at least one chip_confirm submission results in a visibly different taste profile summary — confirmed items read as assertive, rejected items as explicit negatives, pending items as probabilistic observations with signal counts.
- **SC-005**: No regeneration cycle ever mutates a confirmed chip's status or selection round, and no chip_confirm submission ever mutates a confirmed chip; status integrity for confirmed chips holds across at least 100 regeneration cycles and chip_confirm submissions in evaluation. Rejected chips may be re-surfaced as pending when signal count grows, but never promoted directly to confirmed without a user action.
- **SC-006**: The user-context endpoint returns the signal tier and full chip array in a single database round trip with no LLM calls, keeping its median response time below typical read-only endpoint expectations for the service.
- **SC-007**: Chip confirmation returns a successful response before the taste profile rewrite completes; the rewrite completes asynchronously without blocking the user-facing request.
- **SC-008**: At least 90% of users who reach the chip_selection tier complete at least one chip_confirm submission (measured in evaluation / telemetry), demonstrating the flow is obvious and actionable from the messages produced.

## Assumptions

- The existing chip generation job already produces chip entries from signal counts; only its write semantics (adding new pending chips, updating signal counts, preserving confirmed/rejected) need to be adjusted.
- The existing event dispatcher, interaction persistence layer, and domain event model are load-bearing and reused without change — chip_confirm is a new event type in an existing framework.
- The existing consult pipeline, taste regen prompt plumbing, and user-context endpoint already exist from prior features (021 and 022) and this feature extends rather than replaces them.
- The "onboarding message" and "chip selection message" are rendered by the product repo, which reads `signal_tier` and the attached pending chips from `GET /v1/user/context`. This repo does not return a message envelope on `/v1/consult`; exact wording, tone, and localization are product concerns.
- Chip selection uses at least two rounds (round_1 at the lower threshold and round_2 at a higher threshold) to keep the chip UI manageable as the user accumulates more signals.
- Migration safety: adding a nullable metadata column and extending the interaction-type enum are non-destructive operations that run against production without data loss.
