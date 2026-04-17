# Research: Taste Profile & Memory Redesign

**Feature**: 021-taste-profile-memory | **Date**: 2026-04-17

No NEEDS CLARIFICATION items remained after spec and plan authoring. All technical decisions were resolved during the planning phase. This document records the key decisions and their rationale.

---

## R-001: Summary storage format — TEXT vs JSONB

**Decision**: JSONB array of structured objects (`list[SummaryLine]`)
**Rationale**: Consistency with chips (same grounding schema: `source_field`, `source_value`, `signal_count`). Enables mechanical validation — read `signal_count` directly instead of regex parsing `[N signals]` from text. Both artifact types share a single `validate_grounded()` function. Agent read path uses `format_summary_for_agent()` to join back to bullet text — no loss of readability.
**Alternatives considered**:
- TEXT column with bullet-point string: simpler storage, but validation requires regex parsing and summary/chips validation paths diverge.

## R-002: Ranking replacement strategy

**Decision**: Delete RankingService entirely (ADR-058). ConsultService returns candidates in source order (saved first, discovered second). No numeric scoring.
**Rationale**: The EMA taste vector that powered 40% of the ranking score is being deleted. Rather than invent a new numeric proxy from signal_counts, ranking moves to the future agent LLM which can reason over taste_profile_summary in natural language. Returning unranked candidates is acceptable as a transitional state.
**Alternatives considered**:
- Build a new numeric ranker from signal_counts: rejected because signal_counts are categorical (counts by cuisine, subcategory) not dimensional (0.0-1.0 vectors). A numeric formula would be artificial.
- Keep RankingService with only distance/popularity scoring: rejected because taste_similarity was 40% of the score — removing it makes the remaining formula misleading.

## R-003: Debounce strategy — process-local vs distributed

**Decision**: Process-local `dict[user_id, asyncio.Task]` with idempotent regen as the safety net for multi-process overlap.
**Rationale**: Railway runs a single process per service instance. Distributed locking (Redis-based) adds complexity for a rare edge case (two instances handling the same user's saves simultaneously). Since regen is a full overwrite from fresh aggregation, running it twice produces identical results — last-write-wins is correct.
**Alternatives considered**:
- Redis-based distributed lock (e.g., `SET NX` with TTL): rejected as over-engineering for single-process deployment. Can be added later if Railway scales to multiple instances per service.

## R-004: LLM structured output parsing

**Decision**: OpenAI JSON mode with response_format set to the Pydantic schema (`TasteArtifacts`). Parse failure retries once; second failure skips regen.
**Rationale**: GPT-4o-mini supports JSON mode reliably. Pydantic validation catches malformed output. Retry-once handles transient failures without infinite loops. Skipping regen on persistent failure is safe because the next interaction signal will trigger another attempt.
**Alternatives considered**:
- Instructor library for structured output: viable but adds a dependency. OpenAI's native JSON mode is sufficient for this use case (single schema, no nested tool calls).
- No retry: rejected because transient LLM failures are common enough to warrant one retry before giving up.

## R-005: Alembic migration strategy — single vs split

**Decision**: Single migration file with two phases (Phase A: interactions reshape, Phase B: taste_model reshape).
**Rationale**: Both table changes are part of the same feature and must ship together. A partial deployment (interactions reshaped but taste_model not) would leave the system in an inconsistent state. Single migration ensures atomicity.
**Alternatives considered**:
- Two separate migrations: rejected because they must always be applied together, and splitting creates a window where one table is reshaped and the other isn't.

## R-006: Chip validation threshold

**Decision**: Chips with `signal_count < 3` are excluded by the LLM prompt. Post-generation validation confirms this and drops any chip that slipped through. No retry on dropped chips — surviving chips are written as-is.
**Rationale**: A minimum of 3 signals ensures chips represent meaningful patterns, not noise from 1-2 interactions. The LLM prompt enforces this, and validation acts as a safety net. Retrying on drops would add complexity for marginal benefit — the LLM rarely generates chips below the threshold when instructed not to.
**Alternatives considered**:
- No minimum threshold: rejected because 1-2 signal chips would be noisy and misleading for the user.
- Higher threshold (5+): rejected because it would prevent chips from appearing for users with 3-10 interactions, which is the critical early engagement window.
