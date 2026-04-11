# Feature Specification: User Memory Layer

**Feature Branch**: `018-user-memory-layer`  
**Created**: 2026-04-10  
**Status**: Draft  
**Input**: User description: "User memory layer — extract, store, and inject personal facts from user messages"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Personal Fact Captured and Persisted (Priority: P1)

A user sends a consult query that contains a declarative personal fact (e.g., "I use a wheelchair — find me a good sushi spot"). The system extracts the fact at the intent routing step, stores it in the background without delaying the response, and the fact is retrievable on the next call.

**Why this priority**: Core value of the feature — facts must be captured before they can be used. Everything else depends on this working correctly.

**Independent Test**: Can be fully tested by sending a single message with a known personal fact and then reading the `user_memories` table to confirm the row was written with the correct source and confidence.

**Acceptance Scenarios**:

1. **Given** a user sends a message containing "I use a wheelchair", **When** the intent router processes it, **Then** a `PersonalFact` with `text="I use a wheelchair"` and `source="stated"` is extracted.
2. **Given** a personal fact has been extracted, **When** the background task runs, **Then** a row is written to `user_memories` with `source="stated"` and `confidence=0.9`.
3. **Given** the same fact is sent a second time, **When** the background task runs, **Then** no duplicate row is created.
4. **Given** a message with no personal facts, **When** the intent router processes it, **Then** an empty list is returned and no write occurs.

---

### User Story 2 - Stored Memories Injected into Consult Flow (Priority: P2)

On subsequent consult or chat assistant calls, the system loads stored memories for the user and injects them into the processing pipeline (intent parsing, discovery, ranking, response generation). After the ranking step, memories are cleared from context so downstream nodes do not receive them.

**Why this priority**: Without injection, the stored facts have no effect. This is the behavioural payoff of P1.

**Independent Test**: Can be tested by pre-seeding a row in `user_memories`, sending a consult request, and asserting that the injected memories appear in the ranked response (e.g., wheelchair-accessible venues are ranked higher).

**Acceptance Scenarios**:

1. **Given** a user has a stored memory "I use a wheelchair", **When** a new consult request is made, **Then** `load_memories` is called before the pipeline runs and returns the stored text.
2. **Given** memories are loaded, **When** the ranking node completes scoring, **Then** `user_memories` is set to `None` in the graph state.
3. **Given** `user_memories` is `None` after ranking, **When** the response generation node runs, **Then** it does not receive any memory strings.

---

### User Story 3 - Memories Not Injected into Save or Recall Flows (Priority: P3)

When a user sends a save or recall intent, memory loading is skipped entirely. Only consult and chat assistant intents trigger memory injection.

**Why this priority**: Correctness boundary — injecting memories into save/recall flows would be wasteful and could introduce unintended side effects on unrelated pipelines.

**Independent Test**: Can be tested by sending a save-intent message from a user with stored memories and asserting that `load_memories` is never called during that request.

**Acceptance Scenarios**:

1. **Given** a user has stored memories and sends a save-intent message, **When** the pipeline runs, **Then** `load_memories` is not called.
2. **Given** a user has stored memories and sends a recall-intent message, **When** the pipeline runs, **Then** `load_memories` is not called.
3. **Given** a user sends a chat assistant-intent message, **When** the pipeline runs, **Then** `load_memories` is called and memories are injected.

---

### User Story 4 - Place Attributes Excluded from User Facts (Priority: P2)

The system correctly distinguishes between declarative user facts and place attributes. Statements describing a place are never stored as personal facts.

**Why this priority**: Data integrity — storing place attributes as user facts would corrupt the memory model and degrade recommendation quality.

**Independent Test**: Can be tested by sending a message such as "That place is wheelchair-friendly, I loved it" and asserting no row is written for the phrase "wheelchair-friendly" while a row is written for any user-level declaration present.

**Acceptance Scenarios**:

1. **Given** a message containing "This place is wheelchair-friendly", **When** the intent router processes it, **Then** no `PersonalFact` is extracted for that phrase.
2. **Given** a message containing "I use a wheelchair and this place was great for me", **When** the intent router processes it, **Then** a `PersonalFact` for "I use a wheelchair" is extracted but not one for the place description.

---

### Edge Cases

- What happens when a message contains no personal facts? → Empty list returned by intent router; background handler skips all writes.
- What happens when the same fact is submitted multiple times across sessions? → Exact-match deduplication on `(user_id, memory)` prevents duplicate rows.
- What if a message contains both a user fact and a place attribute? → Only the user fact is extracted; the place attribute is filtered out at the LLM prompt level.
- What if a user states a fact that contradicts an earlier memory? → Both facts coexist in storage; no contradiction detection is performed. Deduplication is exact-match only.
- What if the background task fails (e.g., DB error)? → The primary response is already returned; failure is logged but does not surface to the caller.
- What if `load_memories` fails during a consult or assistant call? → Continue without memories — treat as empty list and log the error; the consult request is not blocked.
- What if `user_id` is missing from the request? → Existing request validation rejects the call before reaching the memory layer.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST extract personal facts from every user message, regardless of intent type (save, find, recall, assistant, consult).
- **FR-002**: System MUST extract only declarative user facts — facts about the user ("I use a wheelchair") — never place attributes ("this place is wheelchair-friendly").
- **FR-003**: System MUST classify each extracted fact as either `stated` (explicit first-person declaration) or `inferred` (implied from context).
- **FR-004**: System MUST store extracted personal facts persistently, associated with the originating `user_id`.
- **FR-005**: System MUST assign a confidence of `0.9` to `stated` facts and `0.6` to `inferred` facts; both values MUST be read from configuration, not hardcoded.
- **FR-006**: System MUST skip writing a fact if an identical `(user_id, memory)` pair already exists in storage.
- **FR-007**: System MUST fire a `PersonalFactsExtracted` event after every intent routing call; the event payload carries `user_id` and the extracted facts list (possibly empty).
- **FR-008**: System MUST process the `PersonalFactsExtracted` event in the background — storage writes MUST NOT delay the primary user-facing response.
- **FR-009**: System MUST inject stored user memories into the consult pipeline and the chat assistant service before processing begins.
- **FR-010**: System MUST NOT inject stored user memories into save or recall pipelines.
- **FR-011**: System MUST clear `user_memories` from graph state after the ranking node completes; downstream nodes MUST NOT receive memory strings.
- **FR-012**: System MUST return an empty facts list when no personal facts are present in a message; no storage write occurs in this case.
- **FR-013**: Memories persist indefinitely — the `UserMemoryRepository` Protocol MUST NOT expose a delete operation in this feature.

### Key Entities

- **PersonalFact**: A single declarative fact about a user extracted from a message. Has a text value and a source classification (`stated` or `inferred`).
- **UserMemory**: A persisted personal fact tied to a specific user. Stores the fact text, source, confidence score, and creation timestamp.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Personal facts present in a message are captured and persisted without any measurable increase in the user-facing response time (background task completes asynchronously).
- **SC-002**: Stored memories appear in the context of the very next consult or chat assistant call for the same user — zero-session-gap recall.
- **SC-003**: Zero duplicate fact rows exist per user — repeated submission of identical messages does not increase the row count in `user_memories`.
- **SC-004**: Place attributes are never stored as user memories — a precision rate of 100% on user-fact vs. place-attribute discrimination is the target.
- **SC-005**: Memory injection is absent in save and recall pipeline executions — `load_memories` call count is zero for those intent types.
- **SC-006**: Confidence values in stored rows match the configured thresholds exactly — `stated` rows carry `0.9`, `inferred` rows carry `0.6`.
- **SC-007**: The end-to-end flow (fact in message → stored in DB → injected into next consult) is demonstrable in a single integration test scenario.

## Clarifications

### Session 2026-04-10

- Q: Can stored memories be deleted or do they persist forever? → A: Memories persist forever — no delete method on the repository in this feature. Deletion is deferred to a future feature.
- Q: If loading stored memories fails, should the consult request fail or continue without memories? → A: Continue without memories — treat failure as empty list and log the error; do not surface to the caller.
- Q: Is there a maximum number of memories loaded per user per call? → A: No limit — load all memories for the user.
- Q: When a user states a fact that contradicts a prior memory, what happens? → A: Both facts coexist — no contradiction detection in this feature; dedup is exact-match only.
- Correction: "assistant" intent clarified as the chat assistant service specifically — `load_memories` is called in the chat assistant service handler, not just consult.

## Assumptions

- `user_id` is present in every API request payload; no changes to the request schema are needed to support this feature.
- `load_memories` returns all stored memories for a user — no pagination or limit is applied in this feature.
- "Stated" facts are explicit first-person declarations; "inferred" facts are facts implied from user behaviour or phrasing (e.g., repeated preferences).
- The intent router is the single point of fact extraction — no additional LLM call is introduced for this feature.
- Memory injection means passing loaded memory strings into the prompt context of downstream pipeline nodes (consult) or the system prompt (chat assistant service), not issuing a separate API call.
- The consult pipeline's ranking node is the designated boundary where memories are cleared; the graph state type will be extended to carry an optional `user_memories` field.
- The ADR-043 event dispatcher already supports async background handlers; no new infrastructure is needed beyond registering the new handler.

## Dependencies

- ADR-043: Event dispatcher (existing) — required for `PersonalFactsExtracted` event routing.
- ADR-038: Protocol-based repository pattern — `UserMemoryRepository` must implement a Protocol interface.
- ADR-020: Provider abstraction — no model names hardcoded; any LLM call uses the config-driven role system.
- ADR-010: LangGraph agent graph — defines the node boundaries where memory injection and clearing occur.
- Alembic migration tooling — required to create the `user_memories` table.
- `config/app.yaml` — `memory.confidence.stated` and `memory.confidence.inferred` keys must be added before use.
