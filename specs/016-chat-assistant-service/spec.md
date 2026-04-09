# Feature Specification: Chat Assistant Service

**Feature Branch**: `016-chat-assistant-service`  
**Created**: 2026-04-09  
**Status**: Draft  
**Input**: User description: "Build a conversational place advisor service that takes a user message and returns a direct LLM response. No RAG, no pgvector, no ranking."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ask about a destination's food scene (Priority: P1)

A user asks a broad question about a city or region's food culture — e.g., "What do you think about Tokyo for food?" or "What should I know about eating out in Bangkok as a first-timer?" — and receives a direct, opinionated answer grounded in local knowledge.

**Why this priority**: This is the most common entry point. Users are planning travel or are already somewhere unfamiliar and need orientation, not a search result.

**Independent Test**: Can be fully tested by submitting a destination-level food question and verifying a coherent, opinionated response is returned — not a list of Google-style generic tips.

**Acceptance Scenarios**:

1. **Given** a user asks "What do you think about Tokyo for food?", **When** the request is received, **Then** the assistant returns an opinionated answer covering what makes the city distinctive — not a tourism brochure overview.
2. **Given** a user asks "What should I know about eating out in Bangkok as a first-timer?", **When** processed, **Then** the assistant gives practical, locally-informed guidance with a clear point of view.

---

### User Story 2 - Ask a food knowledge or culture question (Priority: P1)

A user asks a conceptual or cultural question about food — e.g., "What's the difference between izakaya and a regular restaurant?", "Is omakase worth it if I've never tried it?", or "What's the difference between tonkotsu and shoyu ramen?" — and gets a clear, confident answer.

**Why this priority**: Equal to P1 — a large share of messages are knowledge questions, not place queries. The assistant must handle these as naturally as location-based ones.

**Independent Test**: Can be tested by submitting a food knowledge question and verifying the response explains the concept clearly and directly without hedging or over-qualifying.

**Acceptance Scenarios**:

1. **Given** a user asks "What's the difference between tonkotsu and shoyu ramen?", **When** processed, **Then** the assistant clearly distinguishes the two with a direct recommendation on which to try first.
2. **Given** a user asks "Is omakase worth it if I've never tried it?", **When** processed, **Then** the assistant gives an opinionated yes/no answer with practical context — not a list of pros and cons.

---

### User Story 3 - Ask a practical dining etiquette or safety question (Priority: P2)

A user asks a practical question — e.g., "Is tipping expected at restaurants in Japan?", "Is street food in Chiang Mai safe to eat?", or "How do I know if a place is a tourist trap or legit?" — and gets a direct, usable answer.

**Why this priority**: These questions often gate a decision (should I eat this? should I tip?). A hedged or generic answer is useless; confidence is the value.

**Independent Test**: Can be tested by submitting a practical dining question and verifying the response gives a clear actionable answer rather than "it depends."

**Acceptance Scenarios**:

1. **Given** a user asks "Is tipping expected at restaurants in Japan?", **When** processed, **Then** the assistant gives a clear yes/no with cultural context — no diplomatic hedging.
2. **Given** a user asks "Is street food in Chiang Mai safe to eat?", **When** processed, **Then** the assistant gives a direct recommendation with practical guidance on what to look for.

---

### User Story 4 - Ask for a discovery or evaluation strategy (Priority: P3)

A user asks a meta question about how to find good places — e.g., "What's a good way to find local spots when I travel?" or "How do I know if a place is tourist trap or legit?" — and receives concrete, actionable heuristics.

**Why this priority**: Lower frequency but high trust-building value. Users asking this are forming habits, not just making a one-time choice.

**Independent Test**: Can be tested by submitting a discovery strategy question and verifying the response offers specific, opinionated heuristics rather than vague advice.

**Acceptance Scenarios**:

1. **Given** a user asks "What's a good way to find local spots when I travel?", **When** processed, **Then** the assistant offers 2-3 concrete strategies — not a generic "ask locals" tip.
2. **Given** a user asks "How do I know if a place is a tourist trap or legit?", **When** processed, **Then** the assistant gives specific signals to look for, stated confidently.

---

### Edge Cases

- Empty or whitespace-only messages → return HTTP 422 validation error.
- How does the system handle extremely long messages?
- What if the LLM call fails or times out? → Return HTTP 503 with a structured error. No retry, no silent fallback.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept a user message string and a user_id string as input.
- **FR-002**: System MUST return a non-empty conversational text response to every valid message.
- **FR-003**: System MUST use a configurable model role (not a hardcoded model name) to invoke the language model.
- **FR-004**: System MUST attach observability tracing to every language model call.
- **FR-005**: The service MUST be reachable via a versioned HTTP endpoint accepting a POST request.
- **FR-006**: The route handler MUST contain no business logic — it delegates entirely to the service.
- **FR-007**: The assistant persona MUST be that of a knowledgeable food and dining advisor — opinionated, direct, covering place recommendations, food culture, dining etiquette, travel eating, and discovery strategies. Responses must avoid generic travel-guide language and hedged non-answers.
- **FR-008**: System MUST have unit test coverage for the service layer using a mocked language model.
- **FR-009**: If the language model call fails or times out, the system MUST return an HTTP 503 error with a structured error body. No retry, no silent fallback.
- **FR-010**: An empty or whitespace-only message MUST be rejected with an HTTP 422 validation error before reaching the service layer.

### Key Entities

- **ChatRequest**: Represents an inbound query — contains the user's message and their identifier.
- **ChatResponse**: Represents the assistant's reply — contains the response text.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every valid request returns a non-empty text response in under 10 seconds.
- **SC-002**: The assistant persona is consistent across all query types — place queries, food knowledge questions, etiquette questions, and discovery strategy questions all receive direct, opinionated answers without hedging or generic filler.
- **SC-003**: Unit tests pass with a mocked language model, confirming the service layer is independently testable.
- **SC-004**: The endpoint passes linting and static type analysis with no errors.
- **SC-005**: The feature is reachable at a documented, versioned URL immediately after deployment.

## Clarifications

### Session 2026-04-09

- Q: What should the system return when the LLM call fails or times out? → A: Return HTTP 503 with a structured error. No retry, no silent fallback.
- Q: What should the system return for an empty or whitespace-only message? → A: HTTP 422 validation error.
- Q: What is the acceptable response latency for a valid request? → A: Under 10 seconds.

### Session 2026-04-09 (use case expansion)

- Use cases confirmed: destination food scene questions, food knowledge/culture questions (ramen types, omakase, izakaya vs restaurant), dining etiquette questions (tipping, street food safety), and discovery/evaluation strategy questions (how to find local spots, how to spot tourist traps). The assistant scope is broader than local place lookup — it is a food and dining advisor across all these dimensions.

## Assumptions

- No conversation history or multi-turn context is maintained. Each request is stateless.
- The model role `chat_assistant` must be registered in the model configuration before the service can be used.
- No user-specific taste data, saved places, or vector search is involved — responses are purely LLM-generated.
- Standard input validation (non-empty message) is sufficient; no content moderation or filtering is in scope.
- The user_id is passed for tracing/observability purposes and is not used to personalize responses in this iteration.
- The assistant is not geographically constrained — it covers food and dining topics globally.
