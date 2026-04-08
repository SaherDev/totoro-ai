# Research: Extraction Status Polling

## Current State Audit (critical — informs all design decisions)

### What's already built (Run 3)

| Component | Location | State |
|-----------|----------|-------|
| `request_id = str(uuid.uuid4())` | `extraction_pipeline.py:71` | **Done** |
| `ExtractionPending.request_id` field | `types.py:96` | **Done** |
| `ProvisionalResponse.request_id` field | `types.py:79` | **Done** |
| `ExtractPlaceResponse.request_id` field | `api/schemas/extract_place.py` | **Missing — must add** |
| `ExtractionService` passes `request_id` to API response | `service.py:50–56` | **Missing — must wire** |
| `CacheBackend` Protocol | `providers/cache.py` | **Missing — must create** |
| `RedisCacheBackend` | `providers/redis_cache.py` | **Missing — must create** |
| `ExtractionStatusRepository` | `core/extraction/status_repository.py` | **Missing — must create** |
| `ExtractionPendingHandler` writes status to cache | `handlers/extraction_pending.py:46–48` | **Missing — must wire** |
| `GET /v1/extract-place/status/{request_id}` | `routes/extract_place.py` | **Missing — must add** |

### Redis availability

- **Library**: `redis = {version = "^5.0", extras = ["asyncio"]}` — installed.
- **URL config**: `get_secrets().redis.url` via `SecretsConfig.redis.url` (`config.py:307`).
- **No existing Redis client in `providers/`** — `RedisCacheBackend` is the first Redis implementation.
- **Pattern**: Use `redis.asyncio.Redis.from_url(url)` for async client. TTL via `ex=ttl` in `SET`.

---

## Decision 1: CacheBackend Protocol shape

**Decision**: Minimal two-method Protocol: `get(key) → str | None` and `set(key, value, ttl) → None`.

**Rationale**: Only these two operations are needed by `ExtractionStatusRepository`. Keeping the Protocol surface small makes in-memory implementations trivial to write for tests. Adding more methods (delete, expire, exists) would over-specify the interface before there's a use case.

**Alternatives considered**:
- `bytes`-typed return: Rejected — JSON strings are sufficient; avoids encoding complexity.
- Dict-typed value: Rejected — ADR-038 says Protocol methods stay simple; serialization is the repository's concern.

---

## Decision 2: Redis client lifecycle

**Decision**: `RedisCacheBackend` calls `Redis.from_url(url)` once at construction time. The client connection pool is reused across requests.

**Rationale**: `redis.asyncio.Redis.from_url()` creates a connection pool lazily — the object is cheap to construct and safe to share. FastAPI's dependency injection creates a new `RedisCacheBackend` per-request (via `Depends`), but since the connection pool is managed by the `redis` library per URL, this is acceptable for now. If connection pool leaks appear under load, the fix is a singleton pattern — but that is out of scope.

**Alternatives considered**:
- Singleton at module level: Avoids repeated `from_url()` calls, but complicates testing. Deferred until load testing reveals need.
- `aioredis`: Replaced by `redis[asyncio]` in redis-py 5.x — not a separate library.

---

## Decision 3: ExtractionStatusRepository key format

**Decision**: Key format `extraction:{request_id}`, TTL 3600 seconds (1 hour). Value is JSON-serialized `dict`.

**Rationale**: Prefix `extraction:` provides namespace isolation from LLM cache keys (ADR-024 uses `{role}:{hash}` format — no collision). TTL of 3600s matches the spec requirement. Dict-based payload (not Pydantic) avoids a Pydantic import in a repository that should stay thin.

**Alternatives considered**:
- Pydantic serialization: Over-engineered for a read-write cache; `json.dumps/loads` is sufficient.
- Longer TTL: Not warranted — if extraction fails after 1 hour, the user has other recovery paths.

---

## Decision 4: What to write to cache after successful extraction

**Decision**: Write the full `ExtractPlaceResponse`-compatible dict after `persistence.save_and_emit()` completes. On failure, write `{"extraction_status": "failed"}`.

**Rationale**: The status endpoint returns whatever is in the cache directly. Writing the final API response shape means the handler can return it unchanged. This avoids any transformation in the route handler (ADR-034 facade rule).

**Alternatives considered**:
- Write `ExtractionResult` objects: Requires a separate mapping step in the route handler — violates ADR-034.
- Write only a status string: Insufficient for the spec requirement to return full place data on completion.

---

## Decision 5: New ADR required for status endpoint

**Decision**: A new ADR (ADR-048) is required before implementing `GET /v1/extract-place/status/{request_id}`.

**Rationale**: Constitution Section VIII states "Two endpoints only: POST /v1/extract-place and POST /v1/consult." Adding a third endpoint requires a superseding ADR entry per Constitution Section II. ADR-048 extends the API contract to include the polling endpoint.

**Alternatives considered**:
- Treating it as a sub-route of the existing extract-place endpoint (same resource): This is what the implementation does — it lives in `routes/extract_place.py`. An ADR is still needed to update the Constitution record.

---

## Decision 6: request_id in API response

**Decision**: Add `request_id: str | None = None` to `ExtractPlaceResponse`. It is `None` for synchronous (saved/duplicate) responses and a UUID4 string for provisional responses.

**Rationale**: The API schema must carry `request_id` to the product repo. `Optional[str]` is safer than making it required — existing clients that don't use provisional polling won't break.

**Wiring point**: `ExtractionService.run()` at line 50–56 builds the provisional `ExtractPlaceResponse`. It already receives `ProvisionalResponse` with `request_id` populated — just needs to forward it.

---

## Decision 7: ExtractionPendingHandler injection

**Decision**: Inject `ExtractionStatusRepository` via constructor parameter in `ExtractionPendingHandler`. Wire it in `get_event_dispatcher()` in `deps.py` alongside the existing inline construction pattern.

**Rationale**: ADR-019 mandates `Depends()` for all FastAPI-injected dependencies. The `ExtractionPendingHandler` is constructed inline inside `get_event_dispatcher()` (not as a direct FastAPI dependency), so the `ExtractionStatusRepository` is passed to it at construction time, not via `Depends()` on the handler itself. This is consistent with how `pending_persistence` is already constructed inline.

**Alternatives considered**:
- Making `ExtractionPendingHandler` a FastAPI dependency itself: Circular dependency risk already documented in `deps.py:62-65`. Avoid.
