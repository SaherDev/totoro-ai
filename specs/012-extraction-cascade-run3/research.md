# Research: Extraction Cascade Run 3

**Date**: 2026-04-06
**Branch**: 012-extraction-cascade-run3

No NEEDS CLARIFICATION items exist — the spec and ADRs fully specify all decisions.
This document records the binding architectural decisions and integration constraints
that govern implementation of Phases 8–13.

---

## Decision 1: PlaceSaved batching model

**Decision**: Migrate `PlaceSaved.place_id: str` → `place_ids: list[str]`. Dispatch once per extraction run, not once per place.

**Rationale**: ADR-042 defines interaction_count as the number of user interactions, not the number of places. A single TikTok share is one interaction. Dispatching N events for N places would incorrectly inflate interaction_count and distort EMA updates. One event per run, `interaction_count += len(place_ids)`.

**Consumers requiring update**: Three files read `PlaceSaved.place_id` and must be updated atomically:
1. `events.py` — field definition
2. `handlers.py` (`EventHandlers.on_place_saved`) — passes `place_id=event.place_id` to `taste_service.handle_place_saved`
3. `taste/service.py` (`TasteModelService.handle_place_saved`) — iterates interaction log, runs EMA

**Taste model batch semantics**: `handle_place_saved` must:
- Log N `InteractionLog` rows (one per place_id, signal_type=SAVE)
- Run ONE `_apply_taste_update()` with `gain = config.taste_model.signals.save` (not multiplied)
- Call `repository.upsert()` once (not N times)

**Alternatives considered**: Multiplying gain by len(place_ids) — rejected. ADR-042 specifies gain as the signal strength per interaction, not per place. Multiplying would inflate weight beyond what the EMA formula intends.

---

## Decision 2: ExtractionPersistenceService dedup key

**Decision**: Dedup check runs only when `result.external_id is not None`. Skip dedup when external_id is absent.

**Rationale**: The `places` table unique constraint is `(external_provider, external_id)`. If `external_id` is None, the constraint doesn't apply (two rows with the same provider and NULL external_id are allowed). Running dedup with `external_id=None` would call `get_by_provider(provider, None)` and could incorrectly match unrelated places.

**Implementation**: In `save_and_emit`, wrap the dedup check:
```python
if result.external_id is not None:
    existing = await self._place_repo.get_by_provider(result.external_provider or "unknown", result.external_id)
    if existing:
        continue
```

---

## Decision 3: Place.address fallback for nullable ExtractionResult.address

**Decision**: Use `result.address or ""` when constructing `Place` in `save_and_emit`.

**Rationale**: `Place.address` is `Mapped[str]` with `nullable=False` in the DB schema. `ExtractionResult.address: str | None` — the validator may not always resolve an address. Using `""` as a fallback preserves the not-null constraint and keeps the row readable (empty string is queryable).

**Alternatives considered**: Making `Place.address` nullable — rejected. Changing the DB schema requires an Alembic migration and is out of scope for this run. Skipping the save entirely if address is None — rejected. Losing places with a missing address wastes extraction work; the name + Google Place ID are sufficient for display.

---

## Decision 4: ExtractionPersistenceService ordering invariant

**Decision**: `PlaceSaved` dispatch happens AFTER all DB writes and BEFORE the embedding loop. This ordering is immutable.

**Rationale**: ADR-043. If embedding fails, the taste model must still receive the signal. The taste model reads from the interaction_log — it does not query embeddings. Reversing the order (dispatch after embedding) would drop the taste signal on embedding failure.

**Implementation consequence**: The embedding loop uses a broad `except Exception` catch. `VoyageEmbedder.embed()` raises `RuntimeError` specifically, but broad catch protects against future provider changes.

---

## Decision 5: Shared ExtractionPersistenceService instance

**Decision**: `ExtractionPersistenceService` is wired via FastAPI `Depends()` so that `ExtractionService` and `ExtractionPendingHandler` share the same DB session within a request.

**Rationale**: Two separate persistence instances with separate sessions would create a split-brain problem: writes from the inline path and writes from the background path could conflict or miss each other's commits within the same request lifecycle.

**Implementation**: Add `get_extraction_persistence` as a standalone `Depends()` function in `deps.py`. Both `get_extraction_service` and the `ExtractionPendingHandler` construction inside `get_event_dispatcher` call `Depends(get_extraction_persistence)`.

---

## Decision 6: No new ADR required for this run

All architectural patterns used in Phases 8–13 are governed by existing ADRs:
- ADR-008: extract-place is sequential async (ExtractionPipeline, not LangGraph)
- ADR-017/018: Pydantic for all schemas
- ADR-019: FastAPI Depends() for all dependencies
- ADR-034: Route handler is a facade
- ADR-043: Domain event dispatcher pattern
- ADR-046: WholeDocument embedding strategy (description separator from config)

A new ADR would be needed only if the team adopted a new pattern not previously recorded.

---

## Integration Risks

| Risk | Mitigation |
|------|-----------|
| `Place.address` nullable mismatch | Use `result.address or ""` in persistence service |
| `external_provider` can be None in ExtractionResult | Use `result.external_provider or "unknown"` in Place constructor |
| handlers.py missed in Phase 8 PlaceSaved migration | Grep for `place_id` across ALL event/taste files before committing |
| mypy failure at Phase 12 wiring | Hard gate: run `mypy src/` after Phase 11 before Phase 12 begins |
| Breaking API contract | NestJS must update before production deploy; do NOT deploy Phase 12 without coordination |
| ExtractionPendingHandler registered before persistence is wired | Phase 10 must complete before Phase 12 registers the handler |
