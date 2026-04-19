# Internal Contracts: Taste Profile & Memory Redesign

**Feature**: 021-taste-profile-memory | **Date**: 2026-04-17

No new HTTP endpoints. All changes are internal service contracts.

---

## TasteModelService

```python
class TasteModelService:
    async def handle_signal(self, user_id: str, signal_type: InteractionType, place_id: str) -> None
    async def get_taste_profile(self, user_id: str) -> TasteProfile | None
```

- `handle_signal`: INSERT interaction + schedule debounced regen. Called by EventHandlers.
- `get_taste_profile`: Read-only. Returns stored profile or None. No LLM call. Called by future agent.

## TasteModelRepository (Protocol)

```python
class TasteModelRepository(Protocol):
    async def get_by_user_id(self, user_id: str) -> TasteModel | None
    async def upsert_regen(self, user_id: str, signal_counts: dict, summary: list[dict], chips: list[dict], log_count: int) -> None
    async def log_interaction(self, user_id: str, interaction_type: InteractionType, place_id: str) -> None
    async def get_interactions_with_places(self, user_id: str) -> list[InteractionRow]
    async def count_interactions(self, user_id: str) -> int
```

## Pure Functions

```python
def aggregate_signal_counts(rows: list[InteractionRow]) -> SignalCounts
def validate_grounded(artifacts: TasteArtifacts, signal_counts: SignalCounts) -> TasteArtifacts
def format_summary_for_agent(lines: list[SummaryLine]) -> str
def build_regen_messages(signal_counts: SignalCounts, early_signal_threshold: int) -> list[dict[str, str]]
```

## Event Handler Contract (simplified)

All taste handlers delegate to `handle_signal`:

```python
on_place_saved(event)       → handle_signal(user_id, SAVE, place_id) per place
on_recommendation_accepted  → handle_signal(user_id, ACCEPTED, place_id)
on_recommendation_rejected  → handle_signal(user_id, REJECTED, place_id)
on_onboarding_signal        → handle_signal(user_id, ONBOARDING_CONFIRM|DISMISS, place_id)
```

## ConsultService Change

Removed dependencies: `RankingService`, `TasteModelService`
Removed output: `ScoredPlace`
New behavior: return enriched candidates in source order (saved first, discovered second), no numeric score.

## RegenDebouncer

```python
class RegenDebouncer:
    def schedule(self, user_id: str, coro_factory: Callable, delay_seconds: float) -> None
    async def cancel_all(self) -> None  # wired to FastAPI lifespan shutdown
```

Module-level singleton. Process-local `dict[user_id, asyncio.Task]`.
