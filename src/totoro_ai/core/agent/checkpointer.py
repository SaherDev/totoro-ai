"""Postgres-backed checkpointer factory (feature 027 M3, FR-030, research.md R2).

Lazy construction: `build_checkpointer()` is called only on the first
`/v1/chat` request observed with `agent.enabled=true` (FR-018b), not at
startup. The caller (M6's `get_agent_graph` dependency) caches the result.

`setup()` is idempotent — repeated calls do not fail and do not overwrite
existing checkpoints. The three library-owned tables (`checkpoints`,
`checkpoint_blobs`, `checkpoint_writes`) are excluded from Alembic
autogenerate via `alembic/env.py::_include_object` (FR-031).

Pool-sharing with the FastAPI SQLAlchemy engine is deferred to M6+ — see
research.md R2. For M3 the simple `from_conn_string` path is sufficient.
"""

from __future__ import annotations

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from totoro_ai.core.config import get_secrets


async def build_checkpointer() -> AsyncPostgresSaver:
    """Open an `AsyncPostgresSaver` against `DATABASE_URL` and await `setup()`.

    Returns the connected saver. `setup()` creates the library's own
    tables on first call; subsequent calls are no-ops.

    NOTE: the `from_conn_string` helper is an `AbstractAsyncContextManager`
    in `langgraph-checkpoint-postgres ^3`. We enter the context here and
    intentionally do not exit it — the saver is cached for the process
    lifetime by the caller. This matches the documented usage for
    long-lived agents.
    """
    db_url = _normalize_postgres_url(get_secrets().DATABASE_URL)
    cm = AsyncPostgresSaver.from_conn_string(db_url)
    saver: AsyncPostgresSaver = await cm.__aenter__()
    await saver.setup()
    return saver


def _normalize_postgres_url(url: str) -> str:
    """Strip the `+asyncpg` driver suffix — `AsyncPostgresSaver` uses psycopg3.

    Our SQLAlchemy config uses `postgresql+asyncpg://...`, but the
    checkpointer library expects plain `postgresql://...` or
    `postgres://...`. Returning a normalized URL lets callers reuse
    `DATABASE_URL` verbatim.
    """
    if "+asyncpg" in url:
        return url.replace("+asyncpg", "")
    return url
