# Research: Streaming Recommendations via SSE

**Branch**: `001-consult-streaming` | **Date**: 2026-03-17

## Decision: FastAPI SSE streaming via async generator + StreamingResponse

**Decision**: Use `StreamingResponse` from Starlette with an async generator function that yields SSE-formatted strings.

**Rationale**: FastAPI's `StreamingResponse` with `media_type="text/event-stream"` is the correct low-level primitive for SSE. It does not require any additional libraries or decorators. The async generator pattern integrates cleanly with FastAPI's async runtime and supports proper cleanup on client disconnect.

**Alternatives considered**:
- `sse-starlette` library: Rejected — adds a third-party dependency and abstracts away stream control, which the spec explicitly forbids (FR-012).
- Starlette `EventSourceResponse`: Rejected — same library concern, and spec requires raw `StreamingResponse`.

---

## Decision: Client disconnect detection via `request.is_disconnected()` + `try/finally`

**Decision**: Use two complementary mechanisms:
1. `await request.is_disconnected()` checked before each `yield` — breaks the loop when client closes the connection
2. `try/finally` around the generator body — guarantees cleanup of any open resources regardless of how the generator exits

**Rationale**: `request.is_disconnected()` is the FastAPI-idiomatic way to detect client disconnection. `try/finally` is the Python equivalent of Node.js `stream.pipeline()` — both ensure teardown hooks run on disconnect or completion. Together they cover all exit paths: normal completion, early client disconnect, and server-side errors.

Pattern:
```python
async def event_generator(request: Request) -> AsyncGenerator[str, None]:
    try:
        if not await request.is_disconnected():
            yield 'data: {"step": "intent_parsing", "summary": "Parsing intent..."}\n\n'
        if not await request.is_disconnected():
            yield 'data: {"step": "ranking", "summary": "Ranking candidates..."}\n\n'
        if not await request.is_disconnected():
            yield 'data: {"done": true, ...}\n\n'
    except GeneratorExit:
        pass  # generator closed externally
    finally:
        pass  # always runs — close connections, cancel background tasks, log
```

**Alternatives considered**:
- `try/finally` alone: Works but doesn't give early-exit between yields for long-running generators.
- `asyncio.CancelledError` alone: Only raised when the task is explicitly cancelled; not reliably triggered by HTTP client disconnect.

---

## Decision: SSE event format

**Decision**: Each SSE event is a string formatted as `data: {json}\n\n` (double newline terminates the event per SSE spec).

**Rationale**: Standard SSE format. The double newline separates events. JSON payload is serialized inline.

**Format**:
```
data: {"step": "intent_parsing", "summary": "Parsing intent..."}\n\n
data: {"step": "ranking", "summary": "Ranking candidates..."}\n\n
data: {"done": true, "primary": {...}, "alternatives": []}\n\n
```

---

## Decision: StreamingResponse headers

**Decision**: Include headers `Cache-Control: no-cache` and `X-Accel-Buffering: no` to prevent proxy/CDN buffering.

**Rationale**: Without these headers, nginx and CDN proxies may buffer the entire response before forwarding, defeating the purpose of streaming.

```python
StreamingResponse(
    event_generator(),
    media_type="text/event-stream",
    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
)
```

---

## Decision: Route handler returns either StreamingResponse or JSON based on `stream` flag

**Decision**: The route handler checks `request.stream` and returns `StreamingResponse` for streaming mode, or calls the sync service path for JSON mode.

**Rationale**: FastAPI cannot return both `StreamingResponse` and Pydantic models from a single annotated return type. The return type annotation should be `Response` for polymorphic behavior. FastAPI still validates the request schema (Pydantic) regardless.

```python
@router.post("/consult")
async def consult(request: ConsultRequest) -> Response:
    if request.stream:
        return StreamingResponse(service.stream(...), media_type="text/event-stream", headers=...)
    return JSONResponse(await service.consult(...))
```

---

## Decision: Testing SSE with httpx + pytest-asyncio

**Decision**: Use `httpx.AsyncClient` with `app` as transport and `stream()` context manager for streaming tests.

**Rationale**: `TestClient` (sync) supports streaming via `stream=True` but async streams require `httpx.AsyncClient`. Tests assert that the full SSE stream is received and properly terminated.

**Pattern**:
```python
async with httpx.AsyncClient(app=app, base_url="http://test") as client:
    async with client.stream("POST", "/v1/consult", json={...}) as response:
        events = []
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
```

---

## Decision: Phase 1 stub — no LangGraph, no providers, no DB

**Decision**: The stub service yields three hardcoded SSE events (as per spec FR-005). No LLM calls, no DB access, no Redis. LangGraph connects in Phase 4.

**Rationale**: Phase 1 is explicitly a "learning implementation" to validate the streaming infrastructure. The stub makes the endpoint testable immediately without requiring full pipeline infrastructure.

**Consequences**: Service signature is designed to accept the same parameters that the real implementation will use. No breaking changes required when Phase 4 connects the real pipeline.
