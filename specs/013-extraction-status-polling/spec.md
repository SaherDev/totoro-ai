# Feature Specification: Provisional Extraction Status Polling

**Feature Branch**: `013-extraction-status-polling`  
**Created**: 2026-04-07  
**Status**: Draft  
**Input**: User description: "Implement provisional extraction status polling with CacheBackend Protocol, ExtractionStatusRepository, and GET /v1/extract-place/status/{request_id} endpoint"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Submit and Poll for Extraction Result (Priority: P1)

A caller submits a place for extraction (e.g., a TikTok URL with no caption). The system cannot complete the extraction immediately, so it acknowledges the request with a provisional response and a tracking identifier. The caller then polls status at any time using that identifier.

**Why this priority**: This is the core value of the feature — without it, callers have no way to retrieve results from long-running extractions.

**Independent Test**: Can be fully tested by submitting a no-caption TikTok URL, receiving a `provisional: true` response containing a `request_id`, then calling the status endpoint with that `request_id` both before and after background extraction completes.

**Acceptance Scenarios**:

1. **Given** a TikTok URL with no caption is submitted for extraction, **When** the system cannot resolve the place immediately, **Then** the response includes `provisional: true` and a unique `request_id` the caller can use to check back.
2. **Given** a `request_id` returned from a provisional response, **When** background extraction is still in progress, **Then** the status endpoint returns `{"extraction_status": "processing"}`.
3. **Given** a `request_id` returned from a provisional response, **When** background extraction has completed successfully, **Then** the status endpoint returns the full extracted place result.
4. **Given** background extraction completes with no usable result, **When** the caller polls the status endpoint, **Then** the response indicates `{"extraction_status": "failed"}`.

---

### User Story 2 - Safe Polling for Unknown or Expired Requests (Priority: P2)

A caller polls with a `request_id` that does not exist or has expired. The system responds gracefully without errors, treating the state as not-yet-complete.

**Why this priority**: Callers may poll stale or invalid identifiers due to retries, restarts, or TTL expiry. Graceful handling prevents error cascades in the product app.

**Independent Test**: Can be fully tested by calling the status endpoint with a random or expired `request_id` and confirming it returns `{"extraction_status": "processing"}` with a 200 status.

**Acceptance Scenarios**:

1. **Given** a `request_id` that was never created, **When** the status endpoint is called, **Then** the response is `{"extraction_status": "processing"}` with HTTP 200.
2. **Given** a `request_id` whose TTL has expired (after 1 hour), **When** the status endpoint is called, **Then** the response is `{"extraction_status": "processing"}` with HTTP 200.

---

### User Story 3 - Swappable Cache Backend (Priority: P3)

The caching layer used to store and retrieve extraction statuses is abstracted behind a contract, so the underlying storage technology can be changed without modifying callers or business logic.

**Why this priority**: Allows swapping the cache implementation (e.g., in-memory for tests, alternative services for different environments) without affecting the extraction pipeline or the status route.

**Independent Test**: Can be tested by substituting an in-memory cache implementation and confirming all extraction status read/write operations pass without modifying repository or route code.

**Acceptance Scenarios**:

1. **Given** an in-memory cache implementation satisfying the cache contract, **When** used in place of the default implementation, **Then** all status read/write operations behave identically.
2. **Given** the cache contract is defined, **When** status repository code is reviewed, **Then** no direct dependency on any specific cache technology appears in repository or route code.

---

### Edge Cases

- What happens when background extraction is running and the caller polls multiple times? Each call returns `{"extraction_status": "processing"}` until complete.
- What happens if background extraction writes a result and the caller polls before TTL expiry? Returns the full extracted result.
- What happens if the `request_id` contains special characters or unusual formats? The system treats any string as a valid identifier, returning "processing" if not found.
- What happens if the cache write fails after successful extraction? The result is lost; polling returns "processing" indefinitely until TTL expiry (best-effort write, no retry).
- What happens when the same place URL is submitted multiple times? Each submission gets its own `request_id` — no deduplication at this layer.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST return a unique tracking identifier (`request_id`) in every provisional extraction response.
- **FR-002**: System MUST expose a status endpoint that accepts a `request_id` and returns the current extraction state.
- **FR-003**: Status endpoint MUST return `{"extraction_status": "processing"}` when the result is not yet available, including for unknown or expired identifiers.
- **FR-004**: Status endpoint MUST return the full extracted place result when extraction has completed successfully.
- **FR-005**: Status endpoint MUST return `{"extraction_status": "failed"}` when background extraction completed but produced no usable result.
- **FR-006**: System MUST automatically expire stored extraction results after 1 hour.
- **FR-007**: The caching mechanism used for status storage MUST be swappable without changing extraction pipeline or status endpoint code.
- **FR-008**: Status data MUST represent only the final extraction result — intermediate pipeline state MUST NOT be stored.

### Key Entities

- **ExtractionRequest**: A submitted place extraction job identified by a unique `request_id`. Lifecycle: provisional → processing → complete or failed.
- **ExtractionStatus**: The current state of an extraction request. Values: `processing` (default/unknown), `complete` (implied by presence of full result), `failed`. Expires after 1 hour.
- **ProvisionalResponse**: The immediate response returned when extraction cannot complete synchronously. Carries `provisional: true` and the `request_id` for polling.
- **CacheContract**: An abstract interface for storing and retrieving keyed values with TTL. Implementations vary by environment without affecting consumers.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of provisional extraction responses include a `request_id`, enabling status polling without additional coordination.
- **SC-002**: Status endpoint returns a valid response (`processing`, complete result, or `failed`) within 500ms for any `request_id`.
- **SC-003**: Stored extraction results are automatically removed within 5 minutes of the 1-hour TTL expiring.
- **SC-004**: Swapping the cache implementation requires zero changes to the extraction pipeline or status route code.
- **SC-005**: All existing extraction tests continue to pass after the feature is introduced — no regression.

## Assumptions

- The product repo (NestJS) is the primary caller of the status endpoint and will poll at a reasonable frequency (e.g., every 2–5 seconds).
- `request_id` is not authenticated — any caller with the identifier can poll its status. Access control is the product repo's responsibility.
- The 1-hour TTL is sufficient for all background extraction workloads; longer-running jobs are out of scope.
- `request_id` values are universally unique identifiers generated at extraction dispatch time — safe as cache keys with a shared prefix.
- In-memory cache implementations (for testing) need not enforce TTL strictly — TTL enforcement is a property of production cache deployments only.
