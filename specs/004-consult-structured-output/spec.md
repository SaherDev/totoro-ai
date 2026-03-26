# Feature Specification: Consult Endpoint — Structured Output

**Feature Branch**: `004-consult-structured-output`
**Created**: 2026-03-25
**Status**: Draft
**Input**: User description: "Build POST /v1/consult in FastAPI — structured output only. Intent parsing, 6 reasoning steps, Pydantic schemas matching api-contract.md. Phase 2 scope: no pgvector, no Google Places, no ranking."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — NestJS receives a confident place recommendation (Priority: P1)

A NestJS service sends a natural-language consult query on behalf of a user. The AI service parses the user's intent, reasons through a 6-step pipeline, and returns one primary recommendation with up to two alternatives — each with a place name, address, human-readable reasoning, source label, and required photo URL.

**Why this priority**: This is the core value delivery of the consult endpoint. Without a valid structured response, the frontend cannot render a recommendation.

**Independent Test**: Send `POST /v1/consult` with a valid `user_id`, `query`, and `location`. Verify the response matches the contract shape with a populated `primary`, exactly 2 entries in `alternatives`, and all 6 reasoning steps present.

**Acceptance Scenarios**:

1. **Given** a valid request with `user_id`, `query` ("good ramen near Sukhumvit for a date night"), and `location` (lat/lng), **When** the endpoint is called, **Then** the response contains a `primary` with `place_name`, `address`, `reasoning`, `source`, and `photos`; up to 2 `alternatives` with the same fields; and exactly 6 `reasoning_steps` with the identifiers `intent_parsing`, `retrieval`, `discovery`, `validation`, `ranking`, `completion`.
2. **Given** a valid request, **When** the intent is parsed, **Then** the `reasoning_steps[0].summary` reflects the actual parsed fields (e.g., "Parsed: cuisine=ramen, occasion=date night, area=Sukhumvit").

---

### User Story 2 — Intent extraction produces typed structured output (Priority: P1)

The AI service extracts structured intent fields from a free-text query: cuisine type, occasion, price range, radius preference, and any dietary or access constraints. This structured output drives downstream reasoning.

**Why this priority**: Structured intent is the foundation for all recommendation logic. Without it, reasoning steps cannot produce meaningful summaries.

**Independent Test**: Call the intent parser in isolation with a raw query and verify it returns a typed model with the correct fields populated or null where not specified.

**Acceptance Scenarios**:

1. **Given** a query "cheap sushi near me for a quick lunch", **When** intent is parsed, **Then** the result contains `cuisine="sushi"`, `occasion="quick lunch"`, `price_range="low"` (or equivalent), and all required fields present.
2. **Given** a query with ambiguous or missing fields, **When** intent is parsed, **Then** missing fields return `null` (not absent keys), and no 500 error is raised.
3. **Given** a malformed or nonsensical LLM response, **When** schema validation runs, **Then** a 422 error is returned to the caller.

---

### User Story 3 — Reasoning steps carry real data, not generic placeholders (Priority: P2)

Every reasoning step in the response includes a human-readable `summary` that reflects actual data from the pipeline — e.g., counts, detected fields, or outcomes — not boilerplate text.

**Why this priority**: The product repo surfaces these summaries to the frontend. Generic text ("Processing...") breaks the intended transparency and degrades UX quality.

**Independent Test**: Verify that each `reasoning_steps[*].summary` string contains data-specific content (e.g., a parsed field value, a count, or a named result) rather than a static string.

**Acceptance Scenarios**:

1. **Given** a consult request with query "good ramen near Sukhumvit for a date night", **When** the response is returned, **Then** the `intent_parsing` step summary names at least one parsed field (e.g., "Parsed: cuisine=ramen, occasion=date night").
2. **Given** a consult request, **When** the response is returned, **Then** all 6 steps are present in order: `intent_parsing`, `retrieval`, `discovery`, `validation`, `ranking`, `completion`.
3. **Given** a consult request, **When** the response is returned, **Then** each step 2–5 summary references at least one intent-derived value (cuisine, occasion, or location context) — never a "deferred" or "not implemented" message.

---

### User Story 4 — Request validation rejects malformed input (Priority: P2)

The endpoint returns a structured error when required fields are missing or the query is empty, matching the error contract that NestJS expects.

**Why this priority**: NestJS acts on HTTP status codes. Without correct error responses, the product repo cannot surface helpful messages to users.

**Independent Test**: Send requests with missing `user_id`, empty `query`, or no body and verify the appropriate status code and `error_type` in the response.

**Acceptance Scenarios**:

1. **Given** a request with an empty `query` string, **When** the endpoint is called, **Then** a 400 response is returned with `error_type: "bad_request"`.
2. **Given** a request body missing `user_id`, **When** the endpoint is called, **Then** a 422 response is returned automatically.

---

### Edge Cases

- What happens when the query contains only stop words or no meaningful intent?
- How does the system handle `location` being absent (it is optional per the contract)?
- Phase 2 always returns exactly 2 `alternatives` (LLM is prompted for exactly 2); if the LLM fails to produce 2, it is treated as an internal error (500).
- What format are placeholder photo URLs in when no real photo is available?
- When the LLM API is unavailable or times out, the endpoint returns HTTP 500 (`error_type: "internal_error"`). No partial responses. NestJS handles the 500 by returning a 503 with a retry suggestion to the frontend.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept `POST /v1/consult` with `user_id` (string, required), `query` (string, required), and `location` (object with `lat`/`lng` floats, optional).
- **FR-002**: System MUST return a `primary` recommendation with `place_name`, `address`, `reasoning`, `source`, and `photos` — all required fields, none nullable.
- **FR-003**: System MUST return exactly 2 entries in `alternatives` in Phase 2 (LLM is prompted to generate exactly 2). Each entry has the same fields as `primary`. "Up to 2" applies in Phase 3+ where real candidate retrieval may return fewer results.
- **FR-004**: System MUST include exactly 6 `reasoning_steps` in the response, with step identifiers in this order: `intent_parsing`, `retrieval`, `discovery`, `validation`, `ranking`, `completion`.
- **FR-005**: Each `reasoning_steps` entry MUST carry a `summary` that reads as natural product behavior. No phase names, deferral language, or implementation state may appear in any summary — ever. Required patterns (fill with parsed intent; use fallbacks when null):
  - `intent_parsing`: `"Parsed: cuisine=[value], occasion=[value]"` (include only non-null fields)
  - `retrieval`: `"Looking for [cuisine|restaurants] places you've saved near [location|nearby]"`
  - `discovery`: `"Searching for [cuisine|restaurants] restaurants within [radius]km of your location"` (use 1.2km if radius null)
  - `validation`: `"Checking which [cuisine|restaurants] spots are open now"`
  - `ranking`: `"Comparing [cuisine|restaurants] options for [occasion|your criteria]"`
  - `completion`: `"Found your match"`
- **FR-006**: System MUST parse intent from the raw query and extract: `cuisine`, `occasion`, `price_range`, `radius`, and `constraints`. Missing fields return `null`.
- **FR-007**: System MUST return a 400 error with `error_type: "bad_request"` when `query` is empty or missing.
- **FR-008**: System MUST return 422 when intent parsing produces output that fails schema validation.
- **FR-009**: Every LLM call MUST be traced (latency, tokens, input/output) for observability.
- **FR-010**: All model identifiers MUST be resolved from configuration — never hardcoded in application code.
- **FR-011**: The route handler MUST make exactly one service call. No database queries, cache reads, or external API calls may appear in the route file.
- **FR-012**: `photos` MUST be present and non-null in every recommendation (placeholder URLs are acceptable for Phase 2).
- **FR-013**: System MUST provide a Bruno request file for manual end-to-end testing of the endpoint.
- **FR-014**: When any LLM call fails (timeout, API error, rate limit), the endpoint MUST return HTTP 500 with `error_type: "internal_error"`. No partial responses. Exceptions propagate through the existing error handler without suppression.

### Key Entities

- **ConsultRequest**: Represents an incoming recommendation request. Carries `user_id`, `query`, and optional `location` (lat/lng).
- **ParsedIntent**: Structured representation of the user's intent, extracted from the raw query. Fields: `cuisine`, `occasion`, `price_range`, `radius`, `constraints`.
- **Recommendation**: A single place recommendation. Fields: `place_name`, `address`, `reasoning`, `source` (`"saved"` or `"discovered"`), `photos` (required).
- **ReasoningStep**: One step in the agent's reasoning trace. Fields: `step` (string identifier), `summary` (human-readable description with real data).
- **ConsultResponse**: The full recommendation response. Contains `primary` (1 Recommendation), `alternatives` (0–2 Recommendations), `reasoning_steps` (exactly 6 ReasoningSteps).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `POST /v1/consult` returns a valid JSON response matching the API contract on every request with well-formed input.
- **SC-002**: All 6 reasoning steps are present in every successful response, in the correct order, with data-specific summaries.
- **SC-003**: Intent parsing correctly extracts at least `cuisine` and `occasion` from well-formed queries covering standard food/place use cases.
- **SC-004**: The endpoint returns appropriate error status codes (400/422/500) for all invalid input scenarios defined in the API contract.
- **SC-005**: All 3 quality gates pass without intervention: test suite, linter, and type checker all report zero failures.
- **SC-006**: `photos` field is present and non-null in every recommendation in every successful response.
- **SC-007**: End-to-end response time is under 10 seconds for typical queries in a local development environment.

## Clarifications

### Session 2026-03-25

- Q: How strictly does FR-005's "real data" requirement apply to reasoning steps 2–5 in Phase 2? → A: Option C with explicit patterns — summaries must read as natural product behavior using parsed intent fields. No phase/deferral/future-implementation language ever appears. Patterns: retrieval = "Looking for [cuisine] places you've saved near [location]"; discovery = "Searching for [cuisine] restaurants within [radius]km of your location"; validation = "Checking which [cuisine] spots are open now"; ranking = "Comparing [cuisine] options for [occasion]"; completion = "Found your match". Null fallbacks: cuisine → "restaurants", location → "nearby", occasion → sensible default (e.g., "your criteria").
- Q: What is the minimum number of entries required in `alternatives`? → A: Option B — exactly 2 always in Phase 2. GPT-4o-mini generates content, so the prompt controls the count. "Up to 2" in FR-003 covers Phase 3 edge cases (fewer real candidates); Phase 2 always returns exactly 2. Tests assert `len(alternatives) == 2`.
- Q: When the LLM call fails (timeout, API error, rate limit), what should the endpoint return? → A: Option A — HTTP 500 with `error_type: "internal_error"`. Let the exception propagate through the existing error handler. NestJS receives 500 and surfaces a retry suggestion to the user. No partial responses.

## Assumptions

- **Phase 2 scope**: Retrieval (pgvector), Google Places discovery, and ranking are not implemented in this phase. The consult service generates realistic placeholder content using the intent parser and the configured AI model for recommendations.
- **Photos**: Placeholder photo URLs (publicly accessible static images or well-known test URLs) satisfy the `photos` requirement for Phase 2. Real photo fetching is deferred.
- **`location` field**: Optional at the request level. When absent, distance-aware content is omitted from reasoning summaries.
- **`source` field**: Phase 2 will use `"discovered"` as the source for generated recommendations since there is no retrieval from the user's saved collection yet.
- **Observability credentials**: Tracing credentials are expected to be present in the local config. If missing, the service logs a warning and continues rather than failing to start.
- **Model role**: The `intent_parser` logical role is already mapped in the existing config. No config file changes are required.
- **Router registration**: The consult router is already registered in `main.py`. Only the route handler file needs to be created.
