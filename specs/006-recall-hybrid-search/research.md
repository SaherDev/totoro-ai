# Research: Recall Hybrid Search

**Branch**: `006-recall-hybrid-search` | **Date**: 2026-03-31

## 1. Hybrid Search Architecture: pgvector + FTS + RRF

**Decision**: Single SQL CTE query that executes both cosine similarity (pgvector) and full-text search (PostgreSQL FTS) in parallel branches, merged with RRF in one round-trip.

**Rationale**:
- SQLAlchemy ORM cannot express `ROW_NUMBER() OVER (ORDER BY vector <=> :v)` cleanly; raw SQL via `session.execute(text(...))` is the correct path.
- A single CTE avoids N+1 queries: `vector_results` CTE orders by `<=>`, `text_results` CTE orders by `ts_rank`, `combined` CTE FULL OUTER JOINs them and computes RRF score, final SELECT joins back to `places` for full metadata.
- Keeps all ranking logic in the database; Python receives final ordered rows.

**Alternatives considered**:
- Application-level merging (two separate queries, merge in Python): simpler code but two round-trips and Python-side sorting; rejected for unnecessary latency.
- SQLAlchemy ORM with custom types: excessive complexity for ad-hoc ranking query; rejected.

---

## 2. RRF Constant k=60

**Decision**: Use `k=60` (the standard from Cormack et al. 2009).

**Rationale**: Empirically validated across retrieval scenarios regardless of collection size. For collections under 1000 places, k=60 provides reasonable rank spread without special-casing small cardinality. Deviating introduces tuning burden with no evidence of improvement.

**Alternatives considered**: Dynamic k, k=10 — both rejected; no evidence of benefit and add complexity.

---

## 3. FTS on Nullable `cuisine` Column

**Decision**: `to_tsvector('english', place_name || ' ' || COALESCE(cuisine, ''))`.

**Rationale**: `to_tsvector` of NULL returns NULL which breaks `@@` comparisons. `COALESCE(cuisine, '')` contributes no lexemes when NULL but keeps the expression valid. This is the canonical PostgreSQL FTS pattern for optional fields.

**Alternatives considered**: `CASE WHEN cuisine IS NOT NULL THEN ...` — verbose and harder to maintain; rejected.

---

## 4. FTS Index Strategy: Query-Time vs Pre-computed

**Decision**: Query-time `to_tsvector` computation (no pre-computed tsvector column) for the initial implementation.

**Rationale**: Collections under 1000 places per user make query-time FTS fast enough (<50ms). Avoids a new Alembic migration for a generated column and a GIN index at this stage. If scale increases, a generated column + GIN index can be added via migration with no service changes.

**Alternatives considered**: Pre-computed tsvector column + GIN index — justified at 10k+ documents; deferred to future migration.

---

## 5. `match_reason` Derivation Without LLM

**Decision**: Derive from boolean flags (`matched_vector`, `matched_text`) computed in the CTE, resolved to human-readable strings via `CASE` in the final SELECT.

**Rationale**:
- CTE tracks which method contributed each result: `(vr.id IS NOT NULL) AS matched_vector`, `(tr.id IS NOT NULL) AS matched_text`.
- Final `CASE`:
  - Both → `'Matched by name, cuisine, and semantic similarity'`
  - Vector only → `'Matched by semantic similarity'`
  - Text only → `'Matched by name or cuisine'`
  - Embedding fallback → `'Matched by name or cuisine (semantic unavailable)'`
- No LLM call; derivation is deterministic and testable.

**Alternatives considered**: Compute in Python after fetching results — splits logic across layers; rejected.

---

## 6. Embedding Failure Fallback Pattern

**Decision**: `try/except RuntimeError` around `embedder.embed()`, capture `embedding: list[float] | None = None`, branch in repository call.

**Rationale**:
```python
embedding: list[float] | None = None
try:
    vectors = await embedder.embed([query], input_type="query")
    embedding = vectors[0]
except RuntimeError:
    logger.warning("Embedding failed; falling back to text-only search")
```
Repository method signature: `hybrid_search(..., query_vector: list[float] | None, ...)`.
When `query_vector is None`, the repository executes text-only SQL. HTTP 200 is preserved.

**Alternatives considered**: Retry with backoff (adds latency if service is down), fallback to alternate embedder (additional provider dependency) — both rejected.

---

## Summary: Key Constants & Defaults

| Parameter | Value | Source |
|---|---|---|
| RRF k | 60 | Cormack et al. 2009 |
| FTS language | english | Default; no Thai support yet |
| FTS fields | `place_name`, `cuisine` | Feature spec FR-002 |
| Result limit default | 10 | Feature spec FR-005 |
| Embedding dimensions | 1024 | ADR-040 |
| input_type for query | `"query"` | Feature spec (explicit constraint) |
| Candidate pre-fetch multiplier | 2× limit | Standard practice for RRF merging |
