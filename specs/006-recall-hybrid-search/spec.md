# Feature Specification: Recall — Hybrid Place Search

**Feature Branch**: `006-recall-hybrid-search`
**Created**: 2026-03-31
**Status**: Draft

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Natural Language Place Recall (Priority: P1)

A user types a memory fragment ("that cosy ramen spot I saved") and the system returns matching saved places from their collection. The query may be vague, partial, or phrased differently from how the place was originally saved — the system finds it anyway.

**Why this priority**: This is the core value of the recall endpoint. Without this, the feature does not exist.

**Independent Test**: Can be fully tested by sending a recall query for a user who has at least one saved place and verifying that relevant matches are returned with a populated `match_reason`.

**Acceptance Scenarios**:

1. **Given** a user has saved "Fuji Ramen" tagged as ramen, **When** they query "cosy ramen spot", **Then** the system returns "Fuji Ramen" in the results with a non-empty `match_reason`.
2. **Given** a user has multiple saved places across different cuisines, **When** they query "Thai food I loved", **Then** only Thai places appear in the results, ranked by relevance.
3. **Given** a valid query and user_id, **When** the recall request is made, **Then** the response includes `results` (list) and `total` (count), both populated.

---

### User Story 2 - Cross-Method Search Resilience (Priority: P2)

A user's query may match a place by meaning but not by exact text (e.g. "warm noodle place" matching "Fuji Ramen"), or by exact text but not by semantic similarity. The system catches both cases.

**Why this priority**: Hybrid search is the primary quality differentiator. A system that only handles one search path has unacceptable gaps — a user who phrases their query slightly differently would get zero results.

**Independent Test**: Can be tested by constructing two queries: one that matches only via meaning (no overlapping words), and one that matches only via text (exact cuisine/name keyword). Both must return the correct place.

**Acceptance Scenarios**:

1. **Given** a saved place named "Fuji Ramen" (cuisine: ramen), **When** query is "warm noodle bowl place" (no keyword overlap), **Then** the place is still returned via semantic matching and `match_reason` reflects that.
2. **Given** a saved place with a generic description, **When** query is "ramen" (exact keyword match), **Then** the place is returned via text search and `match_reason` reflects that.
3. **Given** a query that matches both search methods, **When** results are returned, **Then** the merged ranking reflects both signals and `match_reason` indicates combined match.

---

### User Story 3 - Cold Start Empty State (Priority: P3)

A new user with no saved places sends a recall query. The system returns a structured empty response — never an error.

**Why this priority**: Empty state handling is a correctness requirement, not a nice-to-have. An error on cold start would break the product's "always returns something" contract and could surface as a 500 to the frontend.

**Independent Test**: Can be fully tested by sending a recall query for a user with zero saved places and verifying the response shape is `{ "results": [], "total": 0, "empty_state": true }` with HTTP 200.

**Acceptance Scenarios**:

1. **Given** a user has no saved places, **When** they send any recall query, **Then** the response is HTTP 200 with `results: []`, `total: 0`, and `empty_state: true`.
2. **Given** a valid user_id with no saves, **When** the recall request is made, **Then** no 4xx or 5xx error is returned under any circumstances.

---

### User Story 4 - Configurable Result Limit (Priority: P4)

The caller can rely on a default result count (10), and the system administrator can adjust the default without code changes.

**Why this priority**: Configurability ensures the system can be tuned per deployment without code changes. Default of 10 is appropriate for a memory/recall UI panel.

**Independent Test**: Can be tested by verifying a user with 20+ saved places only receives 10 results by default.

**Acceptance Scenarios**:

1. **Given** a user has 20 saved places, **When** a recall query matches all of them, **Then** the response contains at most 10 results.
2. **Given** the result limit is changed in configuration, **When** a recall query is made, **Then** the response respects the new limit without any code changes.

---

### Edge Cases

- What happens when the query is a single character or very short string? → System attempts search and returns whatever matches; no validation error for short queries.
- What happens when the user has saved places but none match the query? → Return `{ "results": [], "total": 0, "empty_state": false }` — the user exists but nothing matched.
- What happens when only one search method produces results? → That method's results are returned; the other method contributing zero results is not an error.
- What happens when the query is empty or missing? → Return 400 with a clear error message.
- What happens when the query embedding step fails (embedding service unreachable)? → Fall back to text-only search and still return results. HTTP 200 is preserved; `match_reason` on each result reflects "Matched by text search (semantic unavailable)".

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept a natural language query and a user identifier and return a ranked list of matching saved places belonging to that user.
- **FR-002**: System MUST search saved places using both semantic meaning and textual content, merging results from both methods into a single ranked list.
- **FR-003**: System MUST restrict results to only the places saved by the identified user — results from other users must never appear.
- **FR-004**: System MUST include a `match_reason` field on every result, derived from which search method(s) surfaced the place (not generated by an AI model).
- **FR-005**: System MUST return at most N results per request, where N defaults to 10 and is configurable without code changes.
- **FR-006**: System MUST return HTTP 200 with an empty result list and `empty_state: true` when the user has no saved places.
- **FR-007**: System MUST return HTTP 200 with an empty result list and `empty_state: false` when the user has saves but none match the query.
- **FR-008**: System MUST return HTTP 400 when the query field is empty or missing.
- **FR-009**: System MUST include `place_id`, `place_name`, `address`, `cuisine`, `price_range`, `source_url`, `saved_at`, and `match_reason` in each result.
- **FR-010**: System MUST surface a match found only by text search even when semantic search would not have ranked it highly, and vice versa.
- **FR-011**: System MUST fall back to text-only search and return HTTP 200 when the query embedding step fails — the endpoint must not return a 5xx error due to an embedding service outage.

### Key Entities

- **RecallQuery**: A natural language phrase representing a memory fragment. Paired with a `user_id` that scopes the search to one user's collection.
- **SavedPlace**: A place stored in the user's collection. Has a name, address, cuisine type, price range, optional source URL, and a timestamp of when it was saved.
- **SearchResult**: A SavedPlace enriched with a `match_reason` string that explains why it was surfaced (e.g. "Matched by name and cuisine", "Matched by semantic similarity", "Matched by cuisine keyword").
- **RecallResponse**: The envelope returned to the caller. Contains the ordered list of `SearchResult` items, a `total` count equal to the number of results returned (not the total number matched before the limit), and an optional `empty_state` boolean for the cold-start case.

### Assumptions

- `user_id` is always a valid, authenticated identifier. NestJS validates it before calling this service.
- Saved places have already been stored with searchable content (name and cuisine fields) available at query time.
- The semantic meaning of a place is pre-computed and stored; the query embedding is computed on demand for each recall request.
- Result relevance ranking across both search methods uses Reciprocal Rank Fusion — a standard, parameter-free merging algorithm.
- The result limit default (10) and any future override live in the non-secret application configuration file.
- There is no pagination. The endpoint returns exactly one page of up to N results. Callers cannot request additional pages.

## Clarifications

### Session 2026-03-31

- Q: What happens when the query embedding step fails (embedding service unreachable)? → A: Fall back to text-only search and still return HTTP 200 results.
- Q: Does `total` reflect matched results before the limit or returned results after? → A: Total returned after limit — always equals the length of the `results` array.
- Q: Is pagination (offset/cursor) in scope for this endpoint? → A: No pagination — top-N only; the configurable limit is the complete contract.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Relevant saved places are returned for at least 90% of natural language recall queries that have a matching saved place in the user's collection.
- **SC-002**: A query that would produce zero results from semantic search alone returns the correct place when a text keyword match exists, and vice versa — cross-method recall works in 100% of such cases.
- **SC-003**: A user with zero saved places always receives HTTP 200 with `empty_state: true` — this scenario never produces a 4xx or 5xx error.
- **SC-004**: Every result in the response includes a non-empty `match_reason` that accurately reflects the search method(s) that produced it.
- **SC-005**: Recall queries for collections up to 1,000 saved places return a response in under 2 seconds.
- **SC-006**: The result limit is honoured — a user with 50 saved places receives at most 10 results (default) or the configured maximum.
