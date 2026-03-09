# Alembic Database Setup — totoro-ai

**Goal:** Install Alembic, create SQLAlchemy models for AI tables, run initial migration, confirm FastAPI connects to PostgreSQL, add Redis to docker-compose.

**Architecture:** SQLAlchemy async models + asyncpg driver connect to the shared PostgreSQL instance. Alembic owns migrations for places, embeddings, taste_model only. Redis added to the product repo's docker-compose for local dev.

**Tech Stack:** Alembic, SQLAlchemy (async), asyncpg, pgvector-python, redis-py, PostgreSQL 16 + pgvector 0.5.1

---

## Constitution Check

- [ ] ADR-026: Alembic owns places, embeddings, taste_model migrations ✅ Aligns
- [ ] ADR-026: Never touch users, user_settings, recommendations ✅ Aligns
- [ ] ADR-025: Secrets via config/.local.yaml (DATABASE_URL, REDIS_URL) ✅ Aligns
- [ ] Architecture: SQLAlchemy for DB access (no raw psycopg2) ✅ Aligns
- [ ] No violations found

---

## Phase 1: Install Dependencies

**Checklist:**
- [ ] Task 1.1: Add sqlalchemy, asyncpg, alembic, pgvector, redis to pyproject.toml
- [ ] Task 1.2: Run `poetry install`

**Files:** `pyproject.toml`

**Verify:** `poetry run python -c "import sqlalchemy, alembic, pgvector, redis"`

---

## Phase 2: SQLAlchemy Models

**Checklist:**
- [ ] Task 2.1: Create `src/totoro_ai/db/__init__.py`
- [ ] Task 2.2: Create `src/totoro_ai/db/base.py` — declarative base
- [ ] Task 2.3: Create `src/totoro_ai/db/models.py` — Place, Embedding, TasteModel models
- [ ] Task 2.4: Create `src/totoro_ai/db/session.py` — async engine + session factory

**Schema (confirmed):**
```
places:        id, user_id, place_name, address, cuisine, price_range,
               lat, lng, source_url, validated_at, created_at, updated_at
embeddings:    id, place_id (FK), vector VECTOR(1536), model_name, created_at
taste_model:   id, user_id, model_version, parameters (JSONB),
               performance_score, created_at, updated_at
```

**Files:**
- `src/totoro_ai/db/__init__.py`
- `src/totoro_ai/db/base.py`
- `src/totoro_ai/db/models.py`
- `src/totoro_ai/db/session.py`

**Verify:** `poetry run python -c "from totoro_ai.db.models import Place, Embedding, TasteModel"`

---

## Phase 3: Alembic Setup + Migration

**Checklist:**
- [ ] Task 3.1: Run `poetry run alembic init alembic` to scaffold
- [ ] Task 3.2: Update `alembic.ini` — point script_location to alembic/
- [ ] Task 3.3: Update `alembic/env.py` — load DATABASE_URL from config, import models for autogenerate
- [ ] Task 3.4: Run `poetry run alembic revision --autogenerate -m "init_ai_tables"`
- [ ] Task 3.5: Run `poetry run alembic upgrade head`

**Files:**
- `alembic.ini`
- `alembic/env.py`
- `alembic/versions/xxxx_init_ai_tables.py`

**Verify:** `poetry run alembic upgrade head` → no errors

---

## Phase 4: FastAPI Database Connection

**Checklist:**
- [ ] Task 4.1: Update `config/.local.yaml.example` with DATABASE_URL and REDIS_URL placeholders
- [ ] Task 4.2: Add DB health check endpoint `GET /v1/health` to FastAPI

**Files:**
- `config/.local.yaml.example`
- `src/totoro_ai/api/main.py`

**Verify:** `curl http://localhost:8000/v1/health` → `{"status": "ok", "db": "connected"}`

---

## Phase 5: Docker Compose (Self-Contained)

**Checklist:**
- [ ] Task 5.1: Create `docker-compose.yml` with PostgreSQL + pgvector + Redis
- [ ] Task 5.2: Create `scripts/init-db.sql` to enable pgvector extension

**Files:** `docker-compose.yml`, `scripts/init-db.sql`

**Verify:** `docker ps | grep totoro-ai`

---

## Verify All

- [ ] `poetry run python -c "from totoro_ai.db.models import Place, Embedding, TasteModel"` passes
- [ ] `poetry run alembic upgrade head` runs clean
- [ ] `docker exec totoro-postgres psql -U postgres -d totoro -c "\dt"` shows places, embeddings, taste_model
- [ ] `docker ps | grep totoro-ai` shows postgres + redis running
- [ ] `curl http://localhost:8000/v1/health` returns `{"status": "ok", "db": "connected"}`
