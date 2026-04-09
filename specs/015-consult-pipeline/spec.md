# Feature Specification: Consult Pipeline

**Feature Branch**: `015-consult-pipeline`
**Created**: 2026-04-09
**Status**: Draft
**Input**: User description: "Implement the full consult pipeline as a sequential 6-step workflow covering intent parsing, saved place recall, external discovery, conditional validation, ranking, and response building."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Get a recommendation from saved places nearby (Priority: P1)

A user with saved places asks for a recommendation that matches their current mood and location. The system identifies the right places from their history, scores them against their taste profile, and returns the top match with a clear reason.

**Why this priority**: This is the core value proposition — delivering a personalised recommendation from the user's own saved places. Everything else builds on this.

**Independent Test**: Send a consult request with a query like "sushi nearby" and a lat/lng. Confirm the response contains a ranked place from the saved set with source="saved" and a non-empty reasoning string.

**Acceptance Scenarios**:

1. **Given** a user has saved sushi places and provides their current location, **When** they query "sushi nearby", **Then** the system returns up to 3 ranked results sourced from saved places, ordered by relevance to their taste profile.
2. **Given** a user provides a query with no proximity signal and no lat/lng, **When** the pipeline runs, **Then** distance filtering is skipped and all matching saved places are candidates.
3. **Given** a user has no matching saved places, **When** they query the system, **Then** only discovered candidates are returned.

---

### User Story 2 — Discover external places the user has not saved (Priority: P2)

A user wants recommendations beyond their saved places — either because they have none or because they are exploring somewhere new. The system queries an external places provider and returns relevant results.

**Why this priority**: Discovery fills the gaps when saved places are sparse, making the system useful for new users and new destinations.

**Independent Test**: Send a consult request for a city the user has no saved places in. Confirm the response contains results with source="discovered".

**Acceptance Scenarios**:

1. **Given** no saved places match the query, **When** the system queries the external provider with the resolved location and filters, **Then** discovered candidates are ranked and returned.
2. **Given** a query names a specific destination ("in Tokyo"), **When** the system processes it, **Then** the search is centred on the geocoded coordinates of Tokyo, not the user's current location.
3. **Given** a query contains a specific address, **When** the system processes it, **Then** the search is centred on the geocoded coordinates of that address.

---

### User Story 3 — Only show places that are open now (Priority: P3)

A user asks for a place that is open tonight. The system validates saved candidates against live status and passes the open_now constraint to the external provider.

**Why this priority**: Real-time availability is a common qualifier. Getting it wrong wastes the user's time.

**Independent Test**: Send a query with "open now". Confirm saved candidates are validated against the places provider and closed places are excluded.

**Acceptance Scenarios**:

1. **Given** a query contains "open now", **When** the pipeline runs, **Then** saved candidates are each validated individually and those that fail are removed before ranking.
2. **Given** a query contains "open now", **When** the external provider is called, **Then** the open_now filter is passed so the provider returns only open places.
3. **Given** a query does not contain any availability constraint, **When** the pipeline runs, **Then** saved candidates are not validated and all proceed to ranking.

---

### Edge Cases

- What happens when the intent parser fails (LLM error, timeout, or malformed output)? The pipeline returns HTTP 500 immediately; no degraded run is attempted.
- What happens when the resolved location is null because no location signal is present and no lat/lng was sent? Distance filtering is skipped; distance weight is set to 0 in ranking.
- What happens when the user has zero interactions (empty taste profile)? Ranking falls back to distance, price, and popularity.
- What happens when fewer than 3 candidates survive filtering and validation? The response contains as many results as remain; no padding or error.
- What happens when the external places provider returns no results, or times out, or returns an HTTP error? The pipeline falls back gracefully — saved candidates are returned and no error is propagated to the caller.
- What happens when a saved place has no lat/lng stored? It is excluded from distance filtering but still eligible if distance filtering is skipped.
- What happens when the same place appears in both saved results and external discovery results? Deduplicate by place_id after Step 3; the saved entry is kept and the discovered entry is dropped.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST parse a natural language query into structured intent fields: cuisine, price range, radius, validation flag, discovery filters, and resolved search location.
- **FR-002**: The system MUST resolve the search location entirely during intent parsing — downstream steps receive a lat/lng and never know whether it came from the request, geocoding a city, or geocoding an address.
- **FR-003**: The system MUST fall back to a configured default radius when the intent parser returns null for radius.
- **FR-004**: The system MUST retrieve semantically matching saved places using the raw query, with no location filtering applied at retrieval time.
- **FR-005**: The system MUST apply cuisine, price range, and distance filters to saved place results after retrieval, using parsed intent fields.
- **FR-006**: The system MUST discover external candidate places using the resolved search location and pass discovery filters directly to the external provider for server-side filtering.
- **FR-007**: When the validation flag is true, the system MUST validate each saved candidate against the intent constraints via the external places provider; candidates that fail are removed before ranking.
- **FR-008**: The system MUST rank all surviving candidates using the user's taste profile, with distance used as a scoring dimension when a search location is available.
- **FR-009**: When no taste profile exists for the user, the system MUST rank candidates by distance, price, and popularity.
- **FR-010**: The system MUST return a synchronous JSON response containing up to 3 ranked candidates, each with a source field ("saved" or "discovered") and a reasoning string derived from candidate data.
- **FR-011**: The reasoning string MUST be derived from candidate data fields without any LLM call.
- **FR-012**: The response MUST include a reasoning_steps list that reflects what each pipeline step actually did.
- **FR-013**: The consult endpoint MUST accept requests where photos are absent; photo presence is not required for a valid response.
- **FR-014**: The system MUST deduplicate candidates by place_id after external discovery; when the same place appears in both saved and discovered sets, the saved entry is retained and the discovered entry is dropped.
- **FR-015**: When the external places provider fails (timeout or HTTP error), the system MUST fall back gracefully by continuing with saved candidates only; no error is returned to the caller.
- **FR-016**: When the intent parser fails for any reason, the system MUST return HTTP 500; no degraded or partial pipeline run is attempted.

### Key Entities

- **ParsedIntent**: Structured output of the intent parsing step — cuisine, price range, radius (metres), validation flag, discovery filters, and resolved search location (lat/lng or null).
- **Candidate**: Internal model representing a single place under consideration — includes source, all ranking dimensions (taste signals, popularity, price, distance), and location.
- **PlaceResult**: The external-facing output model for a single recommendation — includes source, reasoning string, and place details.
- **ConsultResponse**: The full API response — contains up to 3 PlaceResult items and a reasoning_steps list.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A consult request with a matching saved place returns at least one result with source="saved" in under 5 seconds end-to-end.
- **SC-002**: A consult request for a location with no saved places returns at least one result with source="discovered" when an external provider is configured.
- **SC-003**: A consult request containing "open now" excludes all saved candidates that the places provider reports as closed.
- **SC-004**: A consult request where no lat/lng is provided and the query names a city returns candidates centred on that city, not the user's device location.
- **SC-005**: 100% of consult responses contain a non-empty reasoning_steps list reflecting actual pipeline execution.
- **SC-006**: Ranking produces a deterministic ordering for the same inputs — no random or LLM-dependent tiebreakers.

## Clarifications

### Session 2026-04-09

- Q: When the same place appears in both saved recall results and external discovery results, which entry wins? → A: Deduplicate by place_id; keep the saved entry and drop the discovered one.
- Q: What should the pipeline do when the external places provider times out or returns an HTTP error? → A: Fall back gracefully — return saved candidates only, no error propagated to the caller.
- Q: What should the pipeline return when the intent parser itself fails (LLM error, timeout, malformed output)? → A: Return HTTP 500 — intent parsing is a hard prerequisite; no degraded run.

## Assumptions

- The intent parser is capable of geocoding city names, neighbourhood names, and street addresses into lat/lng coordinates as part of its structured output — no separate geocoding service is required for this feature.
- The external places provider accepts open_now, type, and keyword as filter parameters.
- The taste profile service returns an empty or zero vector when the user has no interactions; no separate "has interactions" check is needed before ranking.
- Photos are optional on every place result; the feature does not require them to be populated.
- Streaming SSE responses are deferred — synchronous JSON is the delivery format for this feature.
- Parallel execution of recall and discovery is deferred — sequential execution is the target for this feature.
- The pipeline focuses on food and cuisine as the primary use case in this iteration; no place type should be hard-coded as a default.
