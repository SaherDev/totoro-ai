# Feature Specification: Schema, Repository, and Code Quality Fixes

**Feature Branch**: `003-fix-schema-repo-quality`
**Created**: 2026-03-25
**Status**: Draft
**Input**: User description: Implementation report fixes — C1/C2 (Critical), H1/H2/H3 (High), M1/M2 (Medium), L1/L2 (Low)

## Clarifications

### Session 2026-03-25

- Q: Does the Alembic migration for C1 need to preserve existing data? → A: Yes — backfill existing rows by setting `provider='google'` and migrating the current `google_place_id` value into `external_id`. No data loss permitted.
- Q: When the same (provider, external_id) is re-submitted, which fields are updated? → A: All mutable place fields (name, address, category, metadata, etc.) are overwritten with the new values.
- Q: What happens when provider is empty or null on submission? → A: Reject with a validation error — provider is a required, non-empty field.
- Q: Should DB save failures be logged and/or traced? → A: Log only — emit a structured log entry with context (operation, provider, external_id) on every DB save failure. No trace event required.
- Q: How should NestJS embedding dimension verification (SC-005) be done? → A: Not needed — pgvector columns are owned entirely by this repo's Alembic migrations; NestJS never defines vector columns.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Multi-Provider Place Identity (Priority: P1)

As the product team integrates additional place data sources beyond Google, the system must store place identities in a way that is not tied to a single provider. A place from Yelp and a place from Google must coexist without collision, and the same place from the same provider must never be duplicated.

**Why this priority**: The current schema ties place identity to Google's identifier. Adding any other provider (Yelp, Foursquare, TripAdvisor) would break uniqueness guarantees and corrupt the dataset. This is a structural risk that blocks future growth.

**Independent Test**: Can be fully tested by submitting two places — one from Google, one from a second provider — and verifying both persist without error, with no duplicate created when the same place from the same provider is submitted twice.

**Acceptance Scenarios**:

1. **Given** a place identified by Google, **When** the same place is submitted again, **Then** the system updates all mutable fields (name, address, category, metadata) on the existing record rather than creating a duplicate.
2. **Given** two places with the same external ID but from different providers, **When** both are submitted, **Then** both are stored as distinct records without conflict.
3. **Given** a place from a provider other than Google, **When** it is submitted, **Then** it is stored and retrievable with the correct provider label.

---

### User Story 2 - Reliable Place Persistence with Error Recovery (Priority: P2)

When a place is extracted and saved, the operation must either complete fully or roll back cleanly. A partial write — where some data is committed but the record is incomplete — must never happen. If saving fails, the caller receives a clear error with enough context to diagnose the problem.

**Why this priority**: Silent partial writes corrupt the dataset over time and are hard to detect. Explicit failure with rollback ensures data integrity and makes debugging tractable.

**Independent Test**: Can be tested by simulating a database error mid-save and verifying the place record is absent from the database afterward, and the caller receives a structured error response.

**Acceptance Scenarios**:

1. **Given** a successful extraction, **When** saving to the database succeeds, **Then** the full place record is committed and the endpoint returns a success response.
2. **Given** a successful extraction, **When** saving to the database fails partway through, **Then** no partial record exists in the database and the caller receives an error response with context.
3. **Given** the session itself fails during cleanup, **When** the request ends, **Then** any uncommitted changes are rolled back and no data is left in an inconsistent state.

---

### User Story 3 - Complete and Accurate API Documentation (Priority: P3)

Developers integrating the consult endpoint need accurate, complete API documentation to build correct clients. The OpenAPI spec must reflect the actual response shape and status codes for all endpoints, and the API contract document must reflect the actual embedding dimensions in use.

**Why this priority**: Incorrect documentation causes integration bugs that are discovered late. Both the consult endpoint spec and the embedding dimension mismatch affect NestJS integration directly.

**Independent Test**: Can be tested by opening the auto-generated API docs and verifying the consult endpoint lists a 200 response with a documented schema, and by checking the api-contract.md document states 1024 dimensions.

**Acceptance Scenarios**:

1. **Given** the consult endpoint, **When** the API documentation is viewed, **Then** a 200 status code and the response schema are documented.
2. **Given** the api-contract.md document, **When** the embedding dimension field is read, **Then** it shows 1024, matching what the system actually produces.
3. **Given** the NestJS product repo, **When** its data model for embeddings is compared to the documented dimension, **Then** both agree on 1024.

---

### User Story 4 - Stable Deployment Health Checks (Priority: P4)

The system must be reliably detected as healthy by the hosting platform after deployment. The health probe must correctly target the versioned health endpoint so that traffic is only routed to healthy instances.

**Why this priority**: An incorrect or missing health probe means the platform may route traffic to an unhealthy instance, or fail to restart a crashed service.

**Independent Test**: Can be tested by deploying to the staging environment and verifying the platform health check passes and the service receives traffic.

**Acceptance Scenarios**:

1. **Given** a running deployment, **When** the platform runs its health probe, **Then** it hits `/v1/health` and receives a 200 response.
2. **Given** a deployment where the service is not yet ready, **When** the platform runs its health probe, **Then** the probe fails and traffic is not routed to that instance.

---

### Edge Cases

- What happens when the database is unreachable during a save — does the caller receive a structured error or an unhandled exception?
- What happens when a place is submitted with a provider value that is empty or null? → Rejected with a validation error; provider is required and non-empty.
- What happens when the same (provider, external_id) pair is submitted concurrently from two requests — does the uniqueness constraint prevent double-insertion correctly?
- What happens when the health endpoint is queried before the application is fully initialized?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST store place identity as a (provider, external_id) pair, where no two records may share the same pair. On re-submission of an existing pair, all mutable place fields MUST be updated (upsert semantics).
- **FR-002**: The system MUST accept and persist places from any named provider without requiring schema changes per provider. Provider MUST be a non-empty string; requests with a null or empty provider MUST be rejected with a validation error before any database operation.
- **FR-003**: The system MUST roll back all database changes if saving a place fails for any reason, leaving no partial record.
- **FR-004**: The system MUST return a structured error response when a save operation fails, including enough context to identify the cause. The failure MUST also be logged with operation context (provider, external_id) at error level. No trace event is required.
- **FR-005**: The session layer MUST explicitly roll back uncommitted changes when a request ends in error, regardless of implicit database-level behavior.
- **FR-006**: The consult endpoint MUST declare a success status code and a documented response schema in the API specification.
- **FR-007**: The api-contract.md document MUST state the correct embedding dimension (1024) used by the system.
- **FR-008**: The provider access layer MUST expose all public functions through a single, stable public interface so consumers do not bypass it.
- **FR-009**: The deployment configuration MUST specify the health probe path so the hosting platform can correctly detect service readiness.

### Key Entities

- **Place**: Represents a real-world location. Identified uniquely by the combination of the data provider's name and the provider's own identifier for the place.
- **Provider**: A named source of place data (e.g., Google, Yelp, Foursquare). The provider name plus the provider's place ID form a globally unique key.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Places from two different providers with the same external ID can both be stored without error (0 data integrity violations).
- **SC-002**: Submitting the same (provider, external_id) pair twice results in exactly 1 record in the database (no duplicates).
- **SC-003**: A simulated database save failure results in 0 partial records persisted and 100% of such failures returning a structured error to the caller.
- **SC-004**: The consult endpoint appears in the auto-generated API docs with a defined response schema and a 200 status code.
- **SC-005**: The api-contract.md document and the NestJS data model both specify 1024 as the embedding dimension (0 discrepancies).
- **SC-006**: The deployment health probe succeeds on first attempt after a normal startup (probe reliability: 100% for healthy instances).
- **SC-007**: All existing tests pass after the changes and no new quality warnings are introduced (0 regressions).

## Assumptions

- pgvector columns are defined only in this repo's Alembic migrations (1024 dimensions for Voyage 4-lite). NestJS never defines vector columns. No cross-repo verification needed.
- "Explicit rollback" in the session layer is a contract clarification — the database already handles this implicitly, but making it explicit improves readability and safety.
- The health probe fix is a configuration-only change with no application code impact.
- The instructor library type annotation issue is a minor tooling fix and does not affect runtime behavior.
- A "provider" value is a short, stable string identifier (e.g., "google", "yelp"). No registry or validation of valid provider names is required in this iteration.
- The C1 schema migration MUST backfill all existing rows: set `provider='google'` and copy the current `google_place_id` value into `external_id`. The old `google_place_id` column is then dropped in the same migration. No data loss is permitted.
