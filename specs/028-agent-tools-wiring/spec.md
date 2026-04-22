# Feature Specification: Agent Tools & Chat Wiring (M4, M5, M6)

**Feature Branch**: `028-agent-tools-wiring`
**Created**: 2026-04-22
**Status**: Draft
**Input**: User description: "Implement milestones M4, M5, and M6 from docs/plans/2026-04-21-agent-tool-migration.md. This feature covers: dropping IntentParser from ConsultService (M4), building the three tool wrappers for recall, save, and consult (M5), and wiring POST /v1/chat to the agent graph behind the feature flag (M6). The legacy path remains default until M10 in the next feature."

## Clarifications

### Session 2026-04-22

- Q: On the agent path, which value does `ChatResponse.type` carry? → A: Introduce a new literal `"agent"` (additive to the existing type Literal).
- Q: On the flag-off legacy consult dispatch, where do `saved_places` come from? → A: The legacy chat service's consult branch calls the recall service inline and passes the results as the new `saved_places` argument; no fallback is left inside the consult service itself. This scaffolding lives entirely in the chat service and is deleted with the rest of the legacy pipeline in a later feature.
- Q: Are per-tool wall-clock timeouts enforced in this feature? → A: No. All timeout enforcement (`asyncio.wait_for` guards, enriched tracing spans, synthetic-hang tests) is deferred to M9. The `agent.tool_timeouts_seconds` configuration values remain unused in this feature. A deliberately-hung tool will hang the whole chat turn — acceptable because the flag is off by default and M9 ships before the flag flip.

### Session 2026-04-22 — addendum (plan-doc revision)

The plan doc (`docs/plans/2026-04-21-agent-tool-migration.md`) was revised mid-planning to introduce a cross-cutting `EmitFn` primitive callback pattern for reasoning steps. This addendum captures the three derived requirements for this feature:

- **Services emit primitive string tuples.** `RecallService.run`, `ConsultService.consult`, and `ExtractionService.run` each gain an optional `emit: EmitFn | None = None` parameter. `EmitFn` is a `typing.Protocol` (not a plain `Callable` alias) so the third positional argument `duration_ms` can have a default — services may call `emit(step, summary)` or `emit(step, summary, duration_ms=elapsed)` when they have measured the work directly. Either form is valid. Services never construct `ReasoningStep` objects, never set `source` / `tool_name` / `visibility` / `timestamp`, and never know about streaming.
- **`ReasoningStep` gains a `duration_ms: float | None = None` field.** Elapsed time attributed to the step, aligned with structured-logging standards — a primary debugging signal for evals and perf regressions. Populated one of two ways: the service passes it explicitly when it measured the operation (e.g., wrapped a Google Places call in its own timer), or the wrapper's emit closure computes it from timestamp deltas. Always populated in the final persisted `ReasoningStep`; `None` as an input just means "let the wrapper compute it."
- **Parallel-tool-call invariant.** `AgentState.reasoning_steps` has no reducer; each tool's `Command.update` sets the field by concatenating `prior + collected`, so if Sonnet emitted multiple tool calls in a single `AIMessage`, LangGraph's `ToolNode` would run them concurrently and the last-writing tool would overwrite the others' debug/summary steps. The agent system prompt therefore instructs Sonnet to emit **one tool call per response** and to chain sequentially across turns instead of parallelizing within one — this matches the recall → consult design anyway (consult needs `last_recall_results` populated first). A defensive integration test guarding this invariant is explicitly deferred to a later feature (M9) and is out of scope here; this feature ships the prompt instruction and the documented caveat.
- **Tool wrappers own the agent-layer fields and streaming fan-out.** Each wrapper builds an `emit` closure that (a) appends a debug-visibility `ReasoningStep` to a collected list, and (b) fans out to the LangGraph stream writer so live SSE frames fire as each service emit lands. The wrapper appends its own user-visible `tool.summary` step and returns a `Command` that extends `AgentState.reasoning_steps`.
- **`ConsultResponse.reasoning_steps` is deleted.** This field was added to the response schema in earlier work; the plan-doc revision removes it because steps are now delivered live via `emit`, not bundled into the response. Downstream impact: (a) the flag-off legacy chat dispatch does not read the field today, so no behavior change there; (b) `_persist_recommendation` no longer stores reasoning steps in the `Recommendation.response` JSONB column; (c) the existing consult tests that assert on `response.reasoning_steps` are rewritten to spy on the `emit` callback instead.

## Overview

This feature implements the middle three milestones of the agent & tool migration (plan: `docs/plans/2026-04-21-agent-tool-migration.md`, binding ADR-062). The foundation (schema cleanup, inline extraction await, agent graph skeleton, checkpointer) landed in feature 027. This feature delivers the three pieces that make the agent graph usable end-to-end:

- **M4** — ConsultService stops parsing intent and loading its own context. It now takes a pre-parsed query, pre-built filters, pre-loaded saved places, and a pre-composed preference context — all supplied by the caller.
- **M5** — Three async tool wrappers (`recall`, `save`, `consult`) with typed input schemas. Tools read runtime state for user identity and location, write reasoning steps as they run, and chain data through state rather than through LLM-visible arguments.
- **M6** — `POST /v1/chat` becomes flag-aware. With `agent_enabled: false` (the shipped default in this feature), every request continues through the legacy intent-router pipeline. With `agent_enabled: true`, every request flows through the agent graph.

The agent's external behavior stays dark (flag off by default) until a later feature flips the default during canary.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Flag-on conversational turn routed through the agent (Priority: P1)

An operator sets `agent.enabled: true` in configuration. A user sends any message to `POST /v1/chat`. The request is routed to the agent graph. The agent selects the right tool (or answers directly), invokes it, and the response returns with a natural-language reply plus a short, user-visible reasoning trace covering the tool decisions the agent made and a one-line summary of each tool invocation. With the flag off, the same request is served by the legacy intent-router pipeline and behaves identically to today.

**Why this priority**: This is the capability the migration exists to deliver. Without it, M4 and M5 are internal plumbing with no operator-visible outcome. Everything else in this feature is an enabler for this.

**Independent Test**: With the flag on in a dev environment, send the five reference messages from the design doc (a recommendation request, a recommendation with no saves, a pure meta-recall, a save-from-URL, and a direct Q&A). Each returns a coherent reply whose reasoning trace matches the expected shape. Flip the flag off and confirm every request returns to the legacy response shape with zero test regression.

**Acceptance Scenarios**:

1. **Given** the feature flag is off, **When** the user sends any chat message, **Then** the system uses the legacy intent-router dispatch and the response is indistinguishable from pre-feature behavior.
2. **Given** the feature flag is on and the user sends "show me my saved coffee shops", **When** the agent runs, **Then** it calls the recall tool in filter-only mode, the response message lists the saved places, and the user-visible reasoning trace contains exactly one tool-decision step followed by exactly one tool-summary step.
3. **Given** the feature flag is on and the user sends "find me a ramen spot nearby", **When** the agent runs, **Then** it calls recall first and then consult, the response message contains a top pick, and the user-visible reasoning trace alternates tool-decision and tool-summary entries for each tool call (two decisions, two summaries).
4. **Given** the feature flag is on and the user sends "save https://tiktok.com/...", **When** the agent runs, **Then** it calls the save tool, waits for the extraction to complete inline, and the response message confirms the save outcome (saved, duplicate, or needs-review).
5. **Given** the feature flag is on and the user asks a general question ("is tipping expected in Japan?"), **When** the agent runs, **Then** it answers directly without calling any tool and the user-visible trace contains exactly one step (the tool-decision explaining why no tool was needed).
6. **Given** the feature flag is on across two turns sharing the same user identity, **When** turn 2 is sent as a fresh message, **Then** the agent cannot reuse stale saved places from turn 1 — the transient fields are reset at turn boundaries while the conversation history is preserved.

---

### User Story 2 — ConsultService driven by pre-parsed arguments (Priority: P2)

An internal consumer (the agent's consult tool, and during migration the legacy chat pipeline) calls the consult service with a pre-rewritten retrieval query, a typed filter object, a pre-loaded list of the user's saved places, an optional pre-composed preference context, and location. The service performs geocoding (when a location name is supplied), Google Places discovery, merge/dedupe against the caller-supplied saved places, enrichment, warming-tier blending, active-tier chip filtering, and persistence — and returns a ranked recommendation response. The service does not parse natural language, does not load memory, and does not load taste-profile context.

**Why this priority**: M5's tool wrappers need a stable consult signature to close over. This story is a pure internal refactor that is independently mergeable and testable on its own — it delivers developer-visible value (a cleaner service contract) even before the agent path is wired.

**Independent Test**: Unit-test the consult service by calling it with pre-built filter and saved-place fixtures; assert that geocoding, discovery, merge/dedupe, enrichment, blending, chip filtering, and persistence all still run and return the expected shape. Assert the service does not import an intent parser, memory service, or taste-profile loader for the main path.

**Acceptance Scenarios**:

1. **Given** the consult service is called with a pre-built filter carrying a location name, **When** it runs, **Then** it geocodes that name before discovery.
2. **Given** the consult service is called with five saved places plus typical filters, **When** discovery returns additional candidates, **Then** the service merges saved-first, deduplicates by provider identity, enriches the deduped set, and persists a recommendation record.
3. **Given** the consult service is called in warming-signal tier, **When** the candidate blend runs, **Then** the configured discovered-to-saved ratio is applied.
4. **Given** the consult service is called in active-signal tier with rejected chip data, **When** results are assembled, **Then** entries matching rejected chips are filtered out.
5. **Given** the consult service is called with an empty saved-places list and discovery finds results, **When** it runs, **Then** it returns a discovered-only ranked response without error.
6. **Given** the consult service is called with both saved-places and discovery empty, **When** it runs, **Then** it returns an empty result set without throwing, and callers can surface a "nothing matched" response to the user.

---

### User Story 3 — Typed tool wrappers callable by the agent (Priority: P3)

The agent has three tools it can select and invoke. Each tool exposes a typed input schema with human-readable field descriptions. The tools read the user identity and location from runtime state (not from LLM-visible arguments), accept typed filter objects whose shape mirrors the canonical place shape, append structured reasoning steps as they run, and propagate tool-to-tool data through runtime state rather than through the LLM's argument payload. Each tool's docstring specifies how the LLM should rewrite the user's message into the tool's query argument and when to use each mode.

**Why this priority**: M6 cannot invoke the agent without tools. This story is independently testable in isolation — the tools can be assembled into a minimal graph with a stubbed language model and exercised via direct invocations. It delivers value to the agent (the LLM consumer) on its own.

**Independent Test**: Build each tool with mocked underlying services, attach them to an isolated tool node in a throwaway graph, invoke each tool directly with synthetic state, and assert: (a) the input schema does not contain user-identity or location fields; (b) the tool reads those fields from state; (c) each tool appends the expected reasoning steps (one user-visible summary plus its debug sub-steps); (d) recall writes the retrieved places into state where consult can pick them up without the LLM re-serializing them.

**Acceptance Scenarios**:

1. **Given** the recall tool is inspected, **When** its input schema is rendered, **Then** the schema exposes a retrieval-phrase field, a typed filter field, sort-by, and limit — and does not expose user identity or location.
2. **Given** the recall tool is called with a retrieval phrase plus filters, **When** it runs, **Then** the retrieved places are written into runtime state and the tool emits one user-visible summary step plus debug sub-steps describing the retrieval mode and result count.
3. **Given** the recall tool is called with a null retrieval phrase plus filters, **When** it runs, **Then** it operates in filter-only mode (no embedding search) and returns all matches for the filter set.
4. **Given** the recall tool has already populated state in the current turn, **When** the consult tool is called in the same turn, **Then** it reads the saved places from state rather than from LLM-visible arguments — the consult tool's input schema does not expose a saved-places field.
5. **Given** the save tool is called with raw user input, **When** it runs, **Then** it awaits the extraction pipeline inline and surfaces a per-place outcome (saved, duplicate, needs-review) in a single user-visible summary.
6. **Given** a new turn begins on an existing conversation thread, **When** the agent graph is invoked, **Then** the transient tool-chain state (last retrieved places, reasoning steps) is reset while the conversation message history is preserved.
7. **Given** any tool is invoked, **When** its reasoning steps are recorded, **Then** each step carries a source field, a tool-name field, and a visibility field that determines whether the step surfaces to the user or only to debug traces.

---

### Edge Cases

- **Flag-on, agent fails before producing a reply.** When the agent graph exits without a final assistant message (graph error, budget exhausted, no tool selected and no direct response), the fallback node emits a user-visible fallback reasoning step and a generic error-style reply. The legacy pipeline is NOT re-invoked as a backup — the flag is authoritative per request.
- **Flag-on, user's first turn ever.** Conversation history is empty. The agent runs normally; the checkpointer records the first turn under the user's thread identity.
- **Flag-on, user has no saved places.** Recall in recommendation context returns an empty list; the consult tool works with the empty list and returns discovery-only results. The agent composes a reply that acknowledges there was nothing saved to compare against.
- **Flag-on, user's message contains a URL plus a recommendation ask** ("save this and find me similar spots"). The agent chains save → recall — both tool invocations appear in the user-visible trace as alternating decision/summary pairs.
- **Flag-on, agent selects no tool and produces no content.** The agent node synthesizes a fallback reasoning summary from the tool the LLM would have called (if any); if there is no tool and no content, the reasoning step falls back to a neutral "responding directly" line.
- **Flag-on, agent's tool-decision reasoning text exceeds the display cap.** The user-visible reasoning step truncates to a short form; the full text remains available on streaming and tracing channels.
- **Flag-on, back-to-back turns within the TTL window.** The conversation history accumulates; transient fields reset at each turn boundary; the agent cannot pick up stale tool results from the previous turn.
- **Flag-on, LLM emits multiple tool calls in a single response.** The plan constrains tool usage to one call per response; any response with more than one tool call is handled by the graph's tool-node sequencing (calls run in order) but does not split into parallel execution.
- **Flag on but no checkpointer database.** Graph construction fails eagerly at application startup; requests are refused with a 5xx. Operators must provision the checkpointer database before enabling the flag.
- **Flag off, every existing test.** Legacy path continues unchanged; no test change is required for tests that don't exercise the new code paths.

## Requirements *(mandatory)*

### Functional Requirements

**Flag & routing**

- **FR-001**: The system MUST read `agent.enabled` from configuration per request and route the request to either the agent graph or the legacy intent-router pipeline based on the current value.
- **FR-002**: The feature flag MUST default to off in the configuration shipped by this feature. Flipping the default to on is explicitly out of scope (handled in a later feature).
- **FR-003**: When the flag is off, the chat endpoint MUST behave identically to the pre-feature baseline — the same response shape, the same dispatch branches, the same error semantics.
- **FR-004**: When the flag is on, every chat request MUST traverse the agent graph exactly once — there is no intent router in the agent path.

**ConsultService refactor (M4)**

- **FR-005**: The consult service MUST accept a pre-rewritten retrieval query, a typed filter object, a pre-loaded list of the user's saved places, an optional pre-composed preference context, a caller-supplied location, and a signal tier.
- **FR-006**: The consult service MUST NOT internally parse natural language, load user memories, or load the taste-profile summary as main-path context. (A cheap taste-service call scoped to chip filtering MAY remain.)
- **FR-006a**: The consult service MUST accept an optional `emit` callback and call it at each pipeline boundary (geocode, discover, merge, dedupe, enrich, tier_blend, chip_filter) with a primitive `(step_name, summary)` string pair. The consult service MUST NOT construct `ReasoningStep` objects directly and MUST NOT return reasoning steps on the response envelope.
- **FR-006b**: The recall service MUST accept an optional `emit` callback and call it at each pipeline boundary (`recall.mode` after the mode is determined, `recall.result` after the search runs) with primitive string pairs. The recall response envelope MUST NOT gain a reasoning-steps field.
- **FR-006c**: The extraction service MUST accept an optional `emit` callback and call it at each pipeline boundary (`save.parse_input`, `save.enrich`, optional `save.deep_enrichment` when Phase 3 enrichers fire, `save.validate`, `save.persist`) with primitive string pairs. The extraction response envelope shape is unchanged.
- **FR-006d**: The `ConsultResponse.reasoning_steps` field MUST be removed from the response schema. The `_persist_recommendation` helper MUST no longer include reasoning steps in its persisted payload.
- **FR-007**: The consult service MUST continue to geocode named search locations, discover external candidates, merge-and-deduplicate against the caller-supplied saved places, enrich results, apply warming-tier blending, apply active-tier rejected-chip filtering, and persist a recommendation record.
- **FR-008**: The recall filters type and the consult filters type MUST extend a shared base whose fields mirror the canonical place shape (place type, subcategory, tags, nested attributes, source). Each specialized filter type MAY add its own retrieval- or discovery-specific fields.
- **FR-009**: The recall repository's WHERE-clause assembly MUST walk the nested attribute paths on the new filter type rather than the previous flat attribute keys.
- **FR-010**: The existing legacy chat pipeline (flag-off path) MUST continue to work after the refactor. The legacy consult dispatch branch in the chat service builds the new filter object and calls the recall service inline to load the user's saved places, then passes them as the new `saved_places` argument to the refactored consult service. No compatibility fallback is left inside the consult service — the consult service fails loudly if `saved_places` is not supplied. This scaffolding lives entirely in the chat service and is removed along with the rest of the legacy pipeline in a later feature.

**Tool wrappers (M5)**

- **FR-011**: The recall tool MUST expose a typed input schema containing a retrieval-phrase field (nullable, for filter-only mode), a typed filter field, a sort-by enumeration, and a limit. The schema MUST NOT contain user-identity or location fields.
- **FR-012**: The save tool MUST expose a typed input schema containing only the raw user input (URL or free text). The schema MUST NOT contain user-identity or location fields.
- **FR-013**: The consult tool MUST expose a typed input schema containing a retrieval-phrase field, a typed filter field, and an optional preference-context field. The schema MUST NOT contain user-identity, location, or saved-places fields.
- **FR-014**: Each tool's docstring MUST specify how the LLM should rewrite the user's message into the tool's retrieval phrase, including at least two concrete user-message-to-argument examples per tool where applicable.
- **FR-015**: Each tool MUST read user-identity and location from runtime state — the caller of the graph supplies these via the per-turn payload.
- **FR-016**: The recall tool MUST write the retrieved places into runtime state for consumption by the consult tool in the same turn. The consult tool MUST read saved places from runtime state (not from its input schema).
- **FR-017**: Each tool MUST append structured reasoning steps while running. Each reasoning step MUST carry a source field, a tool-name field, a visibility field, a step-name field, and a human-readable summary.
- **FR-017a**: Each tool wrapper MUST supply an `emit` closure to its underlying service. The closure MUST (a) construct a `ReasoningStep` from the primitive `(step_name, summary)` tuple the service passed — stamping `source="tool"`, `tool_name=<the wrapper's tool name>`, `visibility="debug"`, and a timestamp — and append it to a collected list, and (b) fan out the same step to the LangGraph stream writer so live SSE frames fire as each service emit lands (harmless when no stream writer is attached).
- **FR-017b**: The shared helpers used by all three wrappers (`build_emit_closure` and `append_summary`) MUST live in one module so step construction and stream-writer wiring have a single source of truth.
- **FR-017c**: The `build_emit_closure` helper's returned `emit` closure MUST accept an optional `duration_ms` argument. When the caller passes `duration_ms=None` (the default), the closure MUST compute the duration from timestamp deltas — the delta since the previous emit on the same closure, or since the closure was built for the first emit. When the caller passes an explicit `duration_ms`, the closure MUST use the supplied value verbatim. Every resulting `ReasoningStep` MUST carry a non-null `duration_ms`.
- **FR-017d**: The `append_summary` helper's emitted `tool.summary` step MUST carry a `duration_ms` equal to the total elapsed time of the tool invocation — from the first `emit` in the `collected` list to `append_summary`'s call time. When `collected` is empty at `append_summary` time, `duration_ms` MUST be zero.
- **FR-017e**: `ReasoningStep` MUST gain a `duration_ms: float | None = None` field (edit to the model shipped in feature 027). The field MUST be serialized in `ChatResponse.data.reasoning_steps` on the agent path so downstream perf observability can consume it.
- **FR-017f**: The agent system prompt (`config/prompts/agent.txt`, shipped in feature 027) MUST be updated to instruct the orchestrator model to emit exactly one tool call per response and to chain tool calls sequentially across turns rather than in parallel within a single response. This is the primary mitigation for the last-write-wins race on `AgentState.reasoning_steps` described in the Assumptions section.
- **FR-018**: Each tool MUST emit exactly one user-visible summary step per invocation, plus zero or more debug-only sub-steps describing mode, inputs, and intermediate counts.
- **FR-019**: The save tool's user-visible summary MUST convey the per-place outcome (saved, duplicate, needs-review, or failed) using the saved place's name when available.
- **FR-020**: The recall tool's user-visible summary MUST distinguish filter-only mode from search mode and must report the result count.
- **FR-021**: The consult tool's user-visible summary MUST break the result count down by source (saved vs discovered).

**Agent wiring (M6)**

- **FR-022**: The chat service MUST, on the agent path, load the taste-profile summary and the memory summary once per turn, build the per-turn agent payload via the single invocation helper introduced in the foundation, and invoke the compiled agent graph with the user's identity as the thread key.
- **FR-023**: The per-turn agent payload MUST reset the transient tool-chain fields (last retrieved places, reasoning-step list) at every turn boundary.
- **FR-024**: The checkpointer MUST persist conversation history per user identity so multi-turn context survives across requests.
- **FR-025**: The agent graph MUST be constructed lazily at application startup: the checkpointer is built, the tools are built with their underlying services, the language model is bound to the tools, and the compiled graph is cached for reuse across requests.
- **FR-026**: The agent graph construction MUST fail fast at startup if its dependencies (checkpointer, agent prompt with required slots, orchestrator model configuration) are not in place.
- **FR-027**: The chat response on the agent path MUST include the agent's final reply as the user-visible message plus a filtered reasoning-step list containing only steps flagged for user visibility. Debug steps MUST NOT appear in the JSON payload.
- **FR-028**: The chat response on the agent path MUST carry the literal `"agent"` as its type — a new value added to the existing `ChatResponse.type` Literal set alongside the legacy values. Legacy consumers MUST continue to parse the common fields (message, data) without modification; the flag-off default means no consumer sees the new value until a later feature flips the default.
- **FR-029**: Every agent turn MUST open with exactly one user-visible tool-decision reasoning step, even when the agent answers directly without calling a tool.
- **FR-030**: Multi-tool chains MUST produce alternating tool-decision and tool-summary reasoning steps so that each tool call is preceded by a fresh "why did you choose that" explanation.
- **FR-031**: User-visible reasoning-step types MUST be limited to the three declared in the plan (tool-decision, tool-summary, fallback). Any other step MUST be marked debug-only.
- **FR-032**: Tracing MUST remain attached on the agent path — every language-model call and every tool invocation reaches the observability backend via the existing tracing adapter.

**Cross-cutting**

- **FR-033**: Strict type checking MUST remain clean across the refactored surfaces.
- **FR-034**: The existing legacy path tests MUST remain green with the flag off.
- **FR-035**: New tests MUST cover (a) the refactored consult-service contract, (b) each tool's schema and state-reading behavior, (c) the recall-to-consult data handoff via state, (d) the per-turn reset of transient fields across two turns, (e) the reasoning-step visibility filter on the agent path, (f) the four reasoning-step invariants (every-turn opens with a tool-decision; every tool call produces one user-visible summary; tool-name is set on summaries and null on decisions/fallbacks; direct-response turns have exactly one user-visible step), (g) the agent-decision truncation and fallback-on-empty behaviors, and (h) the `emit` callback contract on each service — a spy callback passed to `RecallService.run`, `ConsultService.consult`, and `ExtractionService.run` receives the expected `(step_name, summary)` tuples in the expected order across branch permutations (filter-only vs hybrid recall; geocoded vs non-geocoded consult; warming vs active tier; save success vs duplicate vs needs-review vs failed; Phase 3 enrichers fired vs not).
- **FR-036**: The product repo MUST be coordinated with only to the extent that the new chat response type is introduced; the default flag-off path preserves existing response types, so no product-repo change is required for this feature to ship.
- **FR-037**: The system MUST support multi-turn conversations under the same user identity; the checkpointer persists message history across turns and the agent sees prior exchanges on every new turn.

### Key Entities *(include if feature involves data)*

- **Agent-enabled flag**: A boolean configuration key that, per request, selects between the agent graph and the legacy intent-router pipeline.
- **Consult filters**: A typed object whose structure mirrors the canonical place shape (place type, subcategory, tags, nested attributes, source) plus discovery-specific fields (radius, search-location name, discovery filters).
- **Recall filters**: A typed object with the same canonical-place base plus retrieval-specific fields (max distance, created-after, created-before).
- **Tool reasoning step**: A structured record emitted by the agent or a tool carrying a step name, a human-readable summary, the source (agent, tool, or fallback), the tool name when applicable, a visibility flag (user-facing or debug), a timestamp, and the elapsed time attributed to the step (`duration_ms`).
- **Emit callback**: A small primitive callable — takes a step name and a summary string, returns nothing — that services invoke at each pipeline boundary. The callback contract is type-only (one function signature); each wrapper supplies its own closure that stamps agent-layer fields and fans out to the streaming writer.
- **Agent turn payload**: The per-request update supplied to the graph on invocation — carries the new user message, the taste-profile summary, the memory summary, the user identity, the location, and the reset of transient fields.
- **Agent checkpoint**: The persisted graph state for a user identity after a turn completes — contains accumulated conversation history and is keyed by user identity.
- **Recall tool**: A typed async callable exposing a retrieval-phrase, filters, sort-by, and limit — returns places and writes them into state.
- **Save tool**: A typed async callable exposing only the raw input — awaits extraction inline and returns the per-place outcome.
- **Consult tool**: A typed async callable exposing retrieval phrase, filters, and preference context — merges state-supplied saved places with discovered candidates and returns ranked results.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With the feature flag off, the existing test suite continues to pass with zero regressions (baseline: the current green count on the feature-027 foundation commit).
- **SC-002**: With the feature flag on, each of the five reference chat scenarios (a recommendation with saved matches, a recommendation with no saved matches, a pure meta-recall, a save-from-URL, and a direct Q&A) returns a coherent reply whose user-visible reasoning trace matches the shape described in the plan's worked examples.
- **SC-003**: With the feature flag on, multi-turn conversations preserve conversation history across turns under the same user identity while resetting transient fields at every turn boundary.
- **SC-004**: On the agent path, 100% of user-visible reasoning steps belong to the three declared types (tool-decision, tool-summary, fallback); any other step is classified debug-only and absent from the JSON response.
- **SC-005**: On the agent path, every turn's user-visible reasoning trace starts with exactly one tool-decision step, regardless of whether a tool is called.
- **SC-006**: On the agent path, every tool invocation produces exactly one user-visible summary step; the total user-visible step count per turn is bounded by two plus twice the number of tool calls (one decision per LLM turn, one summary per tool call).
- **SC-007**: The consult service's main-path code has zero references to an intent parser, zero references to a memory loader, and zero references to a taste-profile summary loader (a chip-filtering taste-service call MAY remain).
- **SC-008**: The recall tool, save tool, and consult tool input schemas, when rendered to JSON schema, contain zero fields named user-identity, location, or saved-places. Each schema contains at least the fields declared in its functional requirements.
- **SC-009**: The recall-to-consult data handoff happens via runtime state; the consult tool's LLM-visible argument payload in captured traces never contains saved-place data.
- **SC-010**: On the agent path, every language-model call and every tool invocation appears in the observability backend as a traceable span.
- **SC-011**: Strict type checking and linting across the touched surfaces remain clean.
- **SC-012**: With the feature flag on in a dev environment, the P95 latency for a recall-only turn stays under 4 seconds and for a consult-with-discovery turn stays under 8 seconds (measured over a 20-request smoke run).

## Assumptions

- The agent graph skeleton, agent state type, reasoning-step model, per-turn invocation helper, agent system prompt with required template slots, configuration block for the agent, checkpointer builder, and Alembic exclusion for the library-managed checkpointer tables already exist from feature 027. This feature consumes them rather than building them.
- The canonical place shape and its nested attribute type are already in use end-to-end from feature 019. This feature consumes them for the shared filter base type.
- The extraction service's inline-await behavior is already in place from feature 027. The save tool awaits extraction directly.
- Conversation-history truncation in the checkpointer is deferred to a later feature (risk #1 in the plan). Long histories may push token counts; canary monitoring covers this.
- Streaming support (server-sent events) is deferred to a later feature (M7). This feature ships the tool-side reasoning emission but not the streaming endpoint. Tool invocations that would emit streaming events in the future no-op silently when no writer is attached.
- Interrupt-based clarification flows for low-confidence saves are deferred to a later feature (M8).
- Failure-budget operationalization (per-tool `asyncio.wait_for` guards, enriched tracing spans, synthetic-failure tests) is deferred to a later feature (M9). The M3 skeleton's `max_steps` / `max_errors` counters remain in place and are incremented on raised exceptions during a turn. The `agent.tool_timeouts_seconds` configuration values from feature 027 stay committed but are NOT read or enforced in this feature — a tool hang in this feature hangs the entire chat turn until the underlying service returns or the HTTP client disconnects. This is acceptable because the flag is off by default and M9 ships before any default flip.
- Flipping the default to flag-on, the full canary, and the legacy-code deletion are handled in later features (M10 and M11). This feature leaves the flag off and leaves the legacy pipeline intact.
- Product-repo coordination is minimal: a new chat response type is introduced, but because the flag is off by default the product repo observes no behavior change in this feature's deploy window.

## Dependencies

- Feature 027 (agent foundation) must be merged. This feature builds on its artifacts.
- The feature flag `agent.enabled` remains at its shipped default of off at the end of this feature.
- The legacy intent-router pipeline remains intact at the end of this feature.

## Out of Scope

- Flipping `agent.enabled` default to on.
- Deleting the intent router, intent parser, chat-assistant service, or the corresponding model-role configuration blocks.
- Server-sent-events streaming endpoint for the agent path.
- Interrupt-based clarification turns for needs-review saves.
- Per-tool wall-clock timeout enforcement (`asyncio.wait_for` guards). The `agent.tool_timeouts_seconds` config values committed in feature 027 remain unused until M9.
- Parallelization of recall and consult-discovery within a single turn.
- Per-user feature flags, A/B rollouts, or graduated canaries.
- Schema changes to the external chat contract beyond introducing one new response type value.
