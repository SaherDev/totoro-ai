# Architecture Decisions — Totoro AI

Log of architectural decisions. Add new entries at the top.

Format:

```
## ADR-NNN: Title
**Date:** YYYY-MM-DD\
**Status:** accepted | superseded | deprecated\
**Context:** Why this decision was needed.\
**Decision:** What we decided.\
**Consequences:** What follows from this decision.
```

---

## ADR-042: Cold start thresholds — UX milestone vs. personalization switch

**Date:** 2026-03-25\
**Status:** accepted\
**Context:** Two research documents define different numeric thresholds. The UI flows doc and UX research define 5 saves as the cold start celebration trigger. The taste model research defines 10 interactions as the personalization algorithm switch. These are two different things and must never be conflated.\
**Decision:** 5 saves = UX celebration milestone only. The "Your taste profile is ready" screen and taste chip confirmation flow fire at 5 saves. This is a motivational moment, not a functional claim about personalization quality. 10 interactions = internal personalization switch. The ranking layer moves from Phase 1 (60% cluster-popular / 20% content-based / 20% exploration) to Phase 2 (full collaborative filtering) at 10 interactions. This transition is invisible to the user. No UI element references the 10-interaction threshold.\
**Consequences:** Any UI copy, empty state, or celebration screen referencing personalization readiness uses the 5-save threshold. Any taste model implementation, ranking weight, or phase routing logic uses the 10-interaction threshold. The two thresholds are never mixed in the same layer.

---

## ADR-041: Provider-agnostic place identity via (external_provider, external_id) pair

**Date:** 2026-03-25\
**Status:** accepted\
**Context:** The original schema used a `google_place_id` column as the unique identifier for places. This locks place identity to a single provider — adding Yelp, Foursquare, or any future data source would either break uniqueness guarantees or require per-provider schema changes. The extraction pipeline is designed to support multiple place data sources (ADR-022, ADR-038), so the identity key must match.\
**Decision:** Place identity is stored as a composite `(external_provider, external_id)` pair with a UniqueConstraint enforced at the database level. `external_provider` is a required, non-empty string identifying the data source (e.g. `"google"`, `"yelp"`). `external_id` is the provider's own identifier for the place. Re-submitting an existing `(external_provider, external_id)` pair triggers an upsert — all mutable place fields (name, address, category, metadata) are overwritten with the new values. Submissions with a null or empty `external_provider` are rejected at the API boundary with a 400 validation error before any database operation. The Alembic migration backfills all existing rows by setting `external_provider='google'` and copying the current `google_place_id` value into `external_id`, then drops the old column. No data loss is permitted.\
**Consequences:** Any place data source can be added without schema changes — only a new `external_provider` string value is needed. The NestJS product repo reads and joins on this pair. The migration is a non-destructive backfill, safe to run against environments with existing data. Future provider integrations must supply a stable, non-empty provider identifier and are validated at the extraction boundary before reaching the repository layer.

---

## ADR-040: Voyage 3.5-lite for embeddings with 1024-dimensional vectors

**Date:** 2026-03-16\
**Status:** accepted\
**Context:** Retrieval quality directly determines taste model accuracy and consult recommendation quality. Voyage 3.5-lite outperforms OpenAI text-embedding-3-small by 6.34% on MTEB benchmark. Both cost $0.02/M tokens after free tier, but Voyage's free tier (200M tokens/month recurring) exceeds OpenAI's ($5 one-time credit). Voyage also supports flexible dimensions (256/512/1024/2048) vs OpenAI's fixed 1536, and a 32k token context window vs OpenAI's 8,192. For a portfolio project targeting 94% retrieval accuracy, the retrieval quality advantage is decisive.\
**Decision:** Use Voyage 3.5-lite as the embedding model. Set pgvector column dimensions to 1024 (not 2048, to reduce query latency and storage cost while maintaining quality above the retrieval accuracy target). This choice is locked in before Phase 2 migrations run — changing dimensions mid-project requires re-embedding all saved places. Implement via the provider abstraction layer (ADR-020) so swapping remains possible in the future.\
**Consequences:** Update `EMBEDDING_DIMENSIONS` constant from 1536 to 1024 in `src/totoro_ai/db/models.py`. Create new Alembic migration to set embeddings.vector column to 1024 dimensions before any place embeddings are written. Add `voyage-ai` SDK to `pyproject.toml`. Implement `VoyageEmbedder` class in provider layer. Update `config/models.yaml` with embedder role → voyage-3.5-lite mapping. Update `docs/architecture.md` to reflect Voyage as the embedder. Never use OpenAI for embeddings in this project.

---

## ADR-039: Per-LangGraph-step token and cost logging

**Date:** 2026-03-16\
**Status:** accepted\
**Context:** ADR-010 defines context budgeting between nodes (trim fields per step), but there is no mechanism to measure actual token consumption per step during development. Without logging, you cannot validate that context pruning is working, detect when a single node exceeds budget, or build measurable portfolio claims like "Context pruning reduced token costs by 30% across 50 test queries." Phase 1 LLM Basics recommends per-step token tracking as foundational practice before optimization.\
**Decision:** Every LangGraph node in the consult pipeline logs four metrics after execution: `input_tokens`, `output_tokens`, `model_used`, `cost_usd` (calculated). Logging happens inside the `BaseAgentNode` base class (ADR-035) via Langfuse span properties. Metrics are calculated and included in the response's `reasoning_steps` array (ADR-012) for observability. A `count_tokens(text: str, model: str)` helper function lives in `src/totoro_ai/core/utils/tokens.py` and is used to validate budget estimates during development.\
**Consequences:** Developers see token flow per step during local testing. Langfuse dashboard shows cost breakdown by node and reveals expensive steps. Phase 6 evaluation can claim measured savings with evidence ("pruning reduced cost 30% across 50 test queries"). Expensive or runaway nodes are identified early during implementation.

---

## ADR-038: Protocol abstraction for all swappable dependencies

**Date:** 2026-03-14\
**Status:** accepted\
**Context:** Totoro-ai depends on multiple external systems: LLM providers (OpenAI, Anthropic), embedding models (OpenAI, Voyage), place discovery sources (FSQ local, Google Places), spell correction libraries (symspellpy, pyspellchecker), caching backends (Redis, in-memory), database clients (SQLAlchemy, asyncpg), and any future AI model providers. Without a consistent rule, some dependencies get abstracted and others get hardcoded, creating an inconsistent codebase where swapping one provider is easy and swapping another requires touching business logic. The pattern has already been applied case by case in ADR-020 (LLM and embedding providers) and ADR-032 (spell correction). This ADR makes it a system-wide rule.\
**Decision:** Any dependency that meets one or more of these criteria must be abstracted behind a Python Protocol: (1) has more than one possible implementation now or in the future, (2) is an external system that could be swapped for cost, performance, or availability reasons, (3) needs to be mockable in tests without hitting a real service. This covers but is not limited to: LLM providers, embedding models, place discovery sources, spell correction libraries, caching backends, database repository implementations, external API clients (Google Places, Foursquare, any future data provider), and evaluation model providers. Concrete implementations live in src/totoro_ai/providers/ for cross-cutting dependencies or in the relevant core/ module for domain-specific ones. Service layers, agent nodes, and LangGraph graphs depend on the Protocol only. No concrete class is imported directly in business logic. Active implementation is selected at startup from config/.local.yaml. Swapping any dependency requires a config change and a new implementation class — never a change to business logic.\
**Consequences:** Every new external dependency introduced must be evaluated against the three criteria above before implementation begins. If it qualifies, a Protocol is defined first, then the concrete implementation. Existing dependencies not yet abstracted (Redis cache, database repositories, Google Places client) are brought into compliance as their modules are built. This rule is a Constitution Check item — any plan that introduces a concrete external dependency directly into service or agent code must be flagged and revised before implementation starts.

---

## ADR-037: Chain of Responsibility for candidate validation (deferred)

**Date:** 2026-03-14\
**Status:** deferred\
**Context:** The consult pipeline Step 4 validates candidates against open hours and live signals. As more validation rules are added over time, a single validate_candidate() function will grow into a multi-condition block that is hard to test and extend. Each validation rule is independent and should be able to approve, flag, or reject a candidate without knowing about other rules.\
**Decision:** Deferred. Apply the Chain of Responsibility pattern when Step 4 validators exceed 3 rules. Each validator will be a class implementing a validate(candidate) -> ValidationResult interface. Validators are chained at startup from config. A candidate passes through the full chain unless one validator rejects it outright. Until the threshold is reached, a single validate_candidates() function in the ranking module is acceptable.\
**Consequences:** No implementation now. When the threshold is reached, refactor Step 4 into a chain of validator classes. Each rule becomes independently testable. Adding a new validation rule means adding a new class, not editing existing ones.

---

## ADR-036: Observer pattern for taste model updates via FastAPI background tasks

**Date:** 2026-03-14\
**Status:** accepted\
**Context:** When a user saves a place, the taste model needs to update. If the extraction service calls the taste model service directly, two unrelated concerns are coupled in one function. A failure in taste model update would block the extraction response. The user does not need to wait for the taste model to update before receiving confirmation that their place was saved.\
**Decision:** Place extraction emits a PlaceSaved event after writing to PostgreSQL. The taste model service subscribes and updates via a FastAPI BackgroundTask. The extraction service calls BackgroundTasks.add_task(update_taste_model, user_id, place_id) and returns immediately. The extraction service never imports from the taste model module directly. Implementation pending in Phase 3 when the taste model is built.\
**Consequences:** Extraction and taste model updates are decoupled. Extraction response time is not affected by taste model complexity. A taste model update failure does not affect the user-facing extraction response. Background task failures must be logged and observable via Langfuse. Implementation pending Phase 3.

---

## ADR-035: Template Method pattern for LangGraph node base class

**Date:** 2026-03-14\
**Status:** accepted\
**Context:** The consult pipeline has six LangGraph nodes. Each node receives state, does work, and returns updated state. Without a shared base class, Langfuse tracing and error handling must be added to each node individually. Any change to how tracing is attached or how errors are caught requires editing all six files.\
**Decision:** All LangGraph nodes in the consult pipeline extend BaseAgentNode. The base class defines execute(state: AgentState) -> AgentState as the public interface. It wraps the call in a Langfuse span and catches exceptions, converting them to a structured error state. Subclasses implement _run(state: AgentState) -> AgentState which contains their step-specific logic. The base class never contains business logic. Implementation pending in src/totoro_ai/core/agent/base_node.py.\
**Consequences:** Langfuse tracing and error handling are added once and inherited by all nodes. Adding a new node means subclassing BaseAgentNode and implementing _run only. Changes to tracing or error handling apply to all nodes from one file. Implementation pending.

---

## ADR-034: Facade pattern enforced on FastAPI route handlers

**Date:** 2026-03-14\
**Status:** accepted\
**Context:** FastAPI route handlers for extract-place and consult are entry points into a multi-step pipeline. Without a constraint, Claude Code will inline database queries, Redis calls, and external API calls directly in route files when building quickly. This couples infrastructure to the HTTP layer and makes both harder to test.\
**Decision:** Route handlers are facades. Each handler makes exactly one service call and returns the result. extract_place.py calls ExtractionService.run(raw_input, user_id) only. consult.py calls ConsultService.run(query, user_id, location) only. No SQLAlchemy, no Redis client, no Google Places API calls, no pgvector queries appear in any file under src/totoro_ai/api/routes/. All orchestration lives in the service layer under src/totoro_ai/core/.\
**Consequences:** Route files stay under 30 lines. Infrastructure concerns are testable independently of HTTP routing. Violations of this rule must be flagged during Constitution Check in the Plan phase before implementation begins.

---

## ADR-033: Behavioral Signal Tracking in the Recommendations Table

**Date:** 2026-03-12\
**Status:** accepted\
**Context:** The current recommendations table stores query, data (the full response JSON), and timestamps. This is enough to replay what the system returned but not enough to measure if the system is performing well. The core evaluation metric for Totoro is first recommendation acceptance rate: did the user take the primary recommendation or not? Without storing that signal, there is no way to measure system quality over time, tune the ranking layer, or improve the taste model. Raw typo input has no analytical value and will not be stored. What matters is whether the corrected query produced a recommendation the user accepted.\
**Decision:** Three fields are added to the recommendations table in the Prisma schema: (1) `accepted` (Boolean, nullable) — three explicit states: `true` = user took the primary recommendation; `false` = user picked an alternative or dismissed; `null` = feedback not yet captured (recommendation not yet shown or user has not acted). (2) `shown` (Boolean, non-nullable, default false) — `true` = recommendation was displayed to the user; `false` = recommendation has not been displayed yet. If `shown` is `true` and `accepted` is `null`, this is a negative signal (shown and ignored, gain −0.5 in the taste model). (3) `selected_place_id` (String, nullable) — the place_id of whichever recommendation the user acted on, whether primary or alternative. These fields are written by NestJS after the user signals a choice in the frontend. FastAPI does not write to this table. The frontend sends a lightweight feedback event to NestJS (a single PATCH or POST call) when the user taps a recommendation. NestJS updates the record. No new table is needed. The exact feedback UI mechanic (tap to confirm, explicit accept button, implicit signal from navigation) is an implementation decision deferred to Phase 4 when the agent UI is built. `shown` and `accepted` together produce four meaningful states: `shown=false, accepted=null` = pending (not yet displayed); `shown=true, accepted=null` = shown and ignored (negative signal, gain −0.5); `shown=true, accepted=true` = accepted (positive signal, gain 2.0); `shown=true, accepted=false` = rejected (negative signal, gain −1.5).\
**Consequences:** A Prisma migration adds `accepted`, `shown`, and `selected_place_id` to the recommendations table. `shown` defaults to false and is set to true when NestJS returns the recommendation to the frontend. NestJS needs a feedback endpoint to receive and write the user's choice after a consult response is displayed. The evaluation pipeline in Phase 6 reads `accepted`, `shown`, and `selected_place_id` to compute first recommendation acceptance rate across all users. Recommendations with `shown=true` and `accepted=null` are counted as negative impressions (gain −0.5) in taste model updates. Records with `shown=false` are excluded from accuracy calculations entirely. This schema supports the portfolio claim: first recommendation acceptance rate measured across real user sessions, with impression tracking for negative signal quality.

---

## ADR-032: Spell Correction via Strategy Pattern for Easy Library Swapping

**Date:** 2026-03-12\
**Status:** accepted\
**Context:** Users type casual, unstructured input in two places: the consult query ("cheep diner nerby") and the place sharing input ("fuji raman"). Typos in the consult query can cause the intent parser to misread structured constraints like price or cuisine. Typos in the place sharing input produce a drifted embedding vector, which hurts pgvector retrieval accuracy later. Three Python libraries were evaluated: symspellpy (MIT, free, 700k monthly PyPI downloads, 0.033ms per word at edit distance 2), pyspellchecker (MIT, free, word-by-word Levenshtein correction), and TextBlob (MIT, free, 70% accuracy, known to overcorrect proper nouns and place names). symspellpy is the fastest and most accurate of the three for short multi-word inputs. Correction belongs in FastAPI only. The frontend must not correct spelling because it breaks the conversational feel of the product. NestJS must not correct spelling because it is an auth and routing layer only. Future support for other languages requires different libraries and dictionaries — the implementation must be swappable without changing endpoint handlers.\
**Decision:** A `SpellCorrector` abstract base class defines the contract: `correct(text: str, language: str) -> str`. Implementations wrap different libraries: `SymSpellCorrector` (default, wraps symspellpy), `PySpellCheckerCorrector` (wraps pyspellchecker), future language-specific variants. The active corrector is loaded at FastAPI startup from `config/.local.yaml` under `spell_correction.provider` (e.g., `symspell`, `pyspellchecker`). Both endpoint handlers call `spell_corrector.correct(text, language)` at the start, where language defaults to user's locale from the database. Raw input travels untouched from Next.js through NestJS to FastAPI. FastAPI corrects it silently. The corrected text is what gets embedded, stored in places.place_name, and stored in recommendations.query. The LLM system prompt for intent parsing also includes an explicit instruction to interpret input regardless of spelling as a second layer of tolerance. Google Places API fuzzy matching acts as a third layer for place name typos during validation.\
**Consequences:** A new module `src/totoro_ai/core/spell_correction/` defines `SpellCorrector` base class and concrete implementations. The factory function in `src/totoro_ai/providers/spell_correction.py` reads `config/.local.yaml` and instantiates the active corrector. symspellpy is the initial default in Poetry dependencies. Swapping to a different library requires only a YAML config change and the library dependency installed. Adding support for Thai or Arabic means implementing a new `SpellCorrector` subclass with the appropriate dictionary — endpoint handlers need no changes. The strategy pattern isolates library specifics from business logic.

---

## ADR-031: Agent Skills Integration in Development Workflow

**Date:** 2026-03-12\
**Status:** accepted\
**Context:** The totoro-ai project uses Claude Code with 2 agent skills installed to enhance development efficiency. Without a documented integration strategy, skills may be invoked at suboptimal workflow stages, wasting tokens or missing optimization opportunities.\
**Decision:** Agent skills are scoped to specific workflow stages (from ADR-028) and invoked automatically when task context matches their domain. The mapping is: Clarify _(none)_, Plan _(none)_, Implement `fastapi` (writing/modifying FastAPI routes, schemas, request handlers), Verify _(built-in)_, Complete `use-railway` (deployment, environment config, service provisioning). `fastapi` skill covers route design, dependency injection, request/response validation, middleware. `use-railway` skill covers deployment workflows, environment variables, service provisioning, database configuration. For spec-kit and workflow choices, see `.claude/workflows.md`.\
**Consequences:** Skills are available globally and auto-invoked based on task context. Skills reduce implementation time by providing focused guidance. Claude automatically invokes skills based on domain relevance, eliminating manual configuration. Token efficiency improves through targeted skill use. Future skill additions will extend this table and require ADR update.

---

## ADR-030: Database migration ownership split between Prisma and Alembic

**Date:** 2026-03-09\
**Status:** accepted\
**Context:** Two services write to one shared PostgreSQL instance. Giving Prisma sole ownership of all migrations would require opening the product repo every time FastAPI evolves its AI table schemas. Two separate databases would force HTTP calls or data duplication mid-pipeline, adding latency to the consult agent.\
**Decision:** Split migration ownership by domain. Prisma in the product repo owns and migrates users, user_settings, and recommendations. Alembic in the AI repo owns and migrates places, embeddings, and taste_model. Each tool touches only its own tables. No exceptions.\
**Consequences:** Two migration tools in the system. Accepted because each repo stays autonomous within its domain. Schema changes to AI tables never require opening the product repo and vice versa.

---

## ADR-029: Single committed app.yaml for all non-secret config

**Date:** 2026-03-09 (revised 2026-03-24)\
**Status:** accepted\
**Context:** Non-secret config (app metadata, model roles, extraction weights) was previously merged into `config/.local.yaml` alongside secrets. This made non-secret tuning parameters (confidence weights, thresholds) gitignored and unversioned, meaning different environments could silently diverge and config could not be code-reviewed.\
**Decision:** All non-secret config lives in committed `config/app.yaml` with three top-level keys: `app` (metadata), `models` (logical role → provider/model mapping), `extraction` (confidence weights and thresholds). `config/.local.yaml` (gitignored) holds only true secrets: provider API keys, database URL, Redis URL. Python accesses non-secret config via `get_config() → AppConfig` singleton and secrets via `get_secrets() → SecretsConfig` singleton (both in `core/config.py`). `load_yaml_config()` is an internal loader — consumer code never calls it directly.\
**Consequences:** Non-secret config is versioned, code-reviewable, and consistent across environments. Secrets remain gitignored. The clear boundary — `app.yaml` for config, `.local.yaml` for secrets — prevents future drift back into mixing the two.

---

## ADR-028: 5-Step Token-Efficient Workflow (Clarify → Plan → Implement → Verify → Complete)

**Date:** 2026-03-09\
**Status:** accepted\
**Context:** Previous workflow was unclear about when to use agents, causing token waste through unnecessary subagent dispatches and review loops. Needed a standardized approach that scales from simple 1-file tasks to complex multi-repo changes.\
**Decision:** Adopt 5-step workflow with specific Claude model per step: (1) **Clarify** (Haiku) — If ambiguous, ask 5 questions; (2) **Plan** (Sonnet) — If 3+ files, create docs/plans/*.md with phases + Constitution Check against docs/decisions.md; (3) **Implement** (Haiku/Sonnet per complexity) — Follow plan checklist, write code, commit; (4) **Verify** (Haiku) — Run commands, all must pass; (5) **Complete** (Haiku) — Mark task done. See `.claude/workflows.md` for flow, `.claude/constitution.md` for check process.\
**Consequences:** Average task cost reduced from 250K to 13-18K tokens (~95% savings). Clear decision points on when to plan vs implement. Constitution Check catches architectural violations early (in Plan phase, not Implement phase). Plan doc becomes single source of truth for implementation. Workflow applies consistently across all repos (totoro, totoro-ai, future repos).

---

## ADR-027: _(reserved — unused)_

---

## ADR-026: Per-repo local secrets (FastAPI reads config/.local.yaml)

**Date:** 2026-03-09\
**Status:** accepted\
**Context:** Secrets must never be stored in version control. Each service needs a simple way to manage its own secrets without external dependencies.\
**Decision:** FastAPI reads secrets from `config/.local.yaml` (gitignored, never committed). Developers create this file manually and populate it with their own secret values. No template files, no other files needed. NestJS and Next.js manage secrets in their own `.env.local` files.\
**Consequences:** Simple local setup — create the file and fill in values. CI/CD injects secrets as environment variables at deploy time.

---

## ADR-025: Langfuse callback handler on all LLM invocations

**Date:** 2026-03-07\
**Status:** accepted\
**Context:** Without tracing, there is no visibility into which LLM calls are slow, expensive, or producing bad outputs. Langfuse is already in the stack for monitoring and evaluation.\
**Decision:** Every LLM and embedding call attaches a Langfuse callback handler at invocation time. Implementation pending in `src/totoro_ai/providers/tracing.py`, which will expose a `get_langfuse_handler()` factory. All provider wrappers call it when building `callbacks=` lists. No call goes untraced.\
**Consequences:** Full per-call observability (latency, tokens, cost, input/output). Missing traces in Langfuse indicate a provider call that bypassed the abstraction layer. Implementation pending.

---

## ADR-024: Redis caching layer for LLM responses

**Date:** 2026-03-07\
**Status:** accepted\
**Context:** Repeated identical LLM calls (e.g. same intent string, same place description) waste tokens and add latency. Redis is already in the stack owned exclusively by this repo.\
**Decision:** LLM responses are cached in Redis keyed by a hash of (role, prompt, model, temperature). Cache is applied inside the provider abstraction layer so callers remain unaware. When prompt templates or model config change, cache must be explicitly invalidated. Implementation pending in `src/totoro_ai/providers/cache.py`.\
**Consequences:** Reduces token cost and latency for repeated queries. Requires cache invalidation discipline when prompts or models change. Redis client injected via FastAPI dependency. Implementation pending.

---

## ADR-023: HTTP error mapping from FastAPI to NestJS

**Date:** 2026-03-07\
**Status:** accepted\
**Context:** NestJS acts on HTTP status codes from this service. Without a consistent error contract, the product repo cannot distinguish bad input from internal failures, leading to incorrect user-facing messages.\
**Decision:** FastAPI registers exception handlers that map internal error types to the HTTP codes defined in the API contract: 400 for malformed input, 422 for unparseable intent or no results, 500 for unexpected failures. All error responses return a JSON body with `detail` string. Implementation pending in `src/totoro_ai/api/errors.py`, registered in `api/main.py`.\
**Consequences:** NestJS can reliably act on status codes. 422 triggers a "couldn't understand" message. 500 triggers a 503 with retry suggestion. Implementation pending.

---

## ADR-022: Google Places API client abstraction

**Date:** 2026-03-07\
**Status:** accepted\
**Context:** Google Places API is called in two contexts: validating extracted places (extract-place workflow) and discovering nearby candidates (consult agent). Without abstraction, both callers would duplicate HTTP setup, auth, and error handling.\
**Decision:** A dedicated client class wraps all Google Places API calls. Implementation pending in `src/totoro_ai/core/extraction/places_client.py`. Exposes two methods: `validate_place(name, location)` and `discover_nearby(location, category, radius)`. API key loaded from environment variable, never from config files.\
**Consequences:** Single place for Google Places error handling and response normalization. Both extract-place and consult use the same client. Implementation pending.

---

## ADR-021: LangGraph graph for consult agent orchestration

**Date:** 2026-03-07\
**Status:** accepted\
**Context:** The consult pipeline has six steps with a parallel branch (retrieve + discover) and conditional logic. A sequential async function cannot express the parallel branch or the per-node data contracts cleanly.\
**Decision:** consult is implemented as a LangGraph `StateGraph`. Each pipeline step (intent parsing, retrieval, discovery, validation, ranking, response generation) is a named node. Steps 2 and 3 run as parallel branches per ADR-009. Each node defines its input/output fields explicitly per ADR-010. Implementation pending in `src/totoro_ai/core/agent/graph.py`. Graph is compiled once at startup and invoked per request.\
**Consequences:** Pipeline is inspectable, testable node-by-node, and extensible without touching other nodes. Graph compilation at startup catches schema errors early. Implementation pending.

---

## ADR-020: Provider abstraction layer — config-driven LLM and embedding instantiation

**Date:** 2026-03-07\
**Status:** accepted\
**Context:** Application code must never hardcode model names or provider-specific imports. `config/app.yaml` under `models:` defines logical roles.\
**Decision:** A provider abstraction module reads `config/app.yaml["models"]` and returns initialized LLM and embedding objects keyed by logical role (e.g. `get_llm("intent_parser")`, `get_embedder()`). Implementation in `src/totoro_ai/providers/llm.py`. Swapping a model means changing `app.yaml` only — no code changes.\
**Consequences:** All LLM and embedding calls go through the abstraction. Adding a new provider requires only a new case in the factory function and a YAML entry. Implementation pending.

---

## ADR-019: FastAPI Depends() for database session and Redis client

**Date:** 2026-03-07\
**Status:** accepted\
**Context:** Endpoints for extract-place and consult both need a database connection and Redis client. Without dependency injection, each handler would manage its own connections, making testing and connection pooling harder.\
**Decision:** Database session (SQLAlchemy async session or asyncpg connection) and Redis client are provided via FastAPI `Depends()`. Both dependencies are defined as async generators in `src/totoro_ai/api/deps.py`. Connection pools are created at app startup via lifespan events in `api/main.py`. Implementation pending.\
**Consequences:** Handlers receive typed, lifecycle-managed connections. Tests can override dependencies via `app.dependency_overrides`. Implementation pending.

---

## ADR-018: Separate router modules for extract-place and consult

**Date:** 2026-03-07\
**Status:** accepted\
**Context:** Both endpoints are currently absent from the codebase. Placing them in `main.py` alongside the health check would conflate app bootstrap with business logic and make each endpoint harder to test in isolation.\
**Decision:** Each endpoint lives in its own router module: `src/totoro_ai/api/routes/extract_place.py` and `src/totoro_ai/api/routes/consult.py`. Each module defines its own `APIRouter` with the `/v1` prefix inherited from the parent router in `main.py`. `main.py` includes both routers. Implementation pending.\
**Consequences:** Endpoints are independently testable. Adding a third endpoint means adding a new file, not modifying existing ones. Implementation pending.

---

## ADR-017: Pydantic schemas for extract-place and consult request and response

**Date:** 2026-03-07\
**Status:** accepted\
**Context:** FastAPI validates request bodies and serializes response bodies. Without explicit Pydantic models, validation is implicit and the API contract has no enforceable shape in code.\
**Decision:** All request and response bodies are Pydantic `BaseModel` subclasses defined in `src/totoro_ai/api/schemas.py`. Four models cover the two endpoints: `ExtractPlaceRequest`, `ExtractPlaceResponse`, `ConsultRequest`, `ConsultResponse`. Field names and types match the API contract in `docs/api-contract.md` exactly. Implementation pending.\
**Consequences:** FastAPI returns 422 automatically for malformed requests. Response shapes are enforced at the boundary. Schema changes require updating both the Pydantic model and the API contract doc. Implementation pending.

---

## ADR-016: app.yaml logical-role-to-provider mapping

**Date:** 2026-03-07 (revised 2026-03-24)\
**Status:** accepted\
**Context:** The codebase must never hardcode model names. Provider switching must be a config change, not a code change.\
**Decision:** `config/app.yaml` under the `models:` key maps logical roles — `intent_parser`, `orchestrator`, `embedder`, `evaluator` — to provider name, model identifier, and inference parameters. Read by `providers/llm.py` via `get_config().models[role]` (singleton, no per-call file I/O). Current assignments: `intent_parser` → `openai/gpt-4o-mini`, `orchestrator` → `anthropic/claude-sonnet-4-6-20250514`, `embedder` → `voyage/voyage-3.5-lite`.\
**Consequences:** Swapping any model requires one line change in `app.yaml`. Code that references model names by role rather than string literals is automatically correct after a config change. Adding a new role requires a new YAML entry and a new factory case in the provider layer.

---

## ADR-015: YAML config loader for non-secret settings

**Date:** 2026-03-07\
**Status:** accepted\
**Context:** Non-secret settings (app metadata, model assignments) must live in version-controlled files. Secrets must never appear in config files. A loader that knows where to find config files prevents hardcoded paths throughout the codebase.\
**Decision:** `src/totoro_ai/core/config.py` is the single config module. It exposes two public singletons: `get_config() → AppConfig` (loads `app.yaml` once, cached for process lifetime) and `get_secrets() → SecretsConfig` (loads `.local.yaml` or falls back to env vars once, cached for process lifetime). Internal helpers `load_yaml_config(name)` and `find_project_root()` are implementation details — consumer code never calls them. Config is injectable via FastAPI `Depends(get_config)` / `Depends(get_secrets)`, making it overridable in tests without filesystem I/O.\
**Consequences:** Config is loaded exactly once per process. No per-request file I/O. Tests override config via `app.dependency_overrides`. The clear singleton API prevents ad-hoc `load_yaml_config` calls scattered through the codebase.

---

## ADR-014: `/v1` API prefix via APIRouter loaded from app.yaml

**Date:** 2026-03-07\
**Status:** accepted\
**Context:** The API contract requires all endpoints under `/v1/`. The prefix must not be hardcoded in route decorators so it can be changed in one place if the versioning scheme changes.\
**Decision:** `src/totoro_ai/api/main.py` creates an `APIRouter` with `prefix` loaded from `app.yaml` (`api_prefix: /v1`). All route decorators use paths relative to that prefix (e.g. `/health`, not `/v1/health`). The router is included in the FastAPI app via `app.include_router(router)`.\
**Consequences:** All endpoints are versioned uniformly. Changing the prefix requires one line in `app.yaml`. New routers from other modules must also be included via `app.include_router` to inherit the convention.

---

## ADR-013: SSE streaming as future consult response mode

**Date:** 2026-03-05\
**Status:** accepted\
**Context:** The consult endpoint returns reasoning_steps in a synchronous JSON response. When the frontend needs to show agent thinking in real time, the API contract would need redesigning mid-build without a plan.\
**Decision:** Document SSE as a future response mode now. When needed, FastAPI streams reasoning steps as they complete. The synchronous mode remains the default. No implementation until the frontend requires it.\
**Consequences:** API contract is forward-compatible. NestJS will proxy the SSE stream when the time comes. No work needed today.

---

## ADR-012: reasoning_steps in consult response

**Date:** 2026-03-05\
**Status:** accepted\
**Context:** When a bad recommendation comes back, there is no way to tell if intent parsing failed, retrieval missed the right place, or ranking scored incorrectly. The eval pipeline also needs per-step accuracy measurement.\
**Decision:** The consult response includes a `reasoning_steps` array. Each entry has a `step` identifier and a human-readable `summary` of what happened at that stage.\
**Consequences:** Per-step debugging and evaluation become possible. The product repo consumes and renders these steps. Both repos' API contract docs updated.

---

## ADR-011: Minimal tool registration per consult request

**Date:** 2026-03-05\
**Status:** accepted\
**Context:** Each tool definition costs 100-300 tokens of static context per LLM call. Registering tools the agent never uses wastes tokens at scale.\
**Decision:** Only register tools the agent needs for the current task. Do not preload tools for future capabilities.\
**Consequences:** Saves 600-1,800 tokens per call when 6+ unused tools would otherwise be registered. Tool set must be evaluated per-request.

---

## ADR-010: Context budgeting between LangGraph nodes

**Date:** 2026-03-05\
**Status:** accepted\
**Context:** A raw Google Places response is ~2,000-4,000 tokens. Passing it through validation, ranking, and response generation means paying for those tokens 3 times in 3 LLM calls.\
**Decision:** Each LangGraph node passes only the fields the next node needs. Extract relevant fields (name, address, price, distance, open status) and drop the rest.\
**Consequences:** 80-90% reduction in wasted tokens on forwarded data. Nodes must explicitly define their input/output contracts.

---

## ADR-009: Parallel LangGraph branches for retrieval and discovery

**Date:** 2026-03-05\
**Status:** accepted\
**Context:** Retrieval (pgvector) and discovery (Google Places) are independent steps. Running sequentially wastes wall clock time against the 20s consult timeout.\
**Decision:** Steps 2 (retrieve saved places) and 3 (discover external candidates) run as parallel LangGraph branches. Results merge before validation.\
**Consequences:** ~43% latency reduction on those steps (7s sequential → 4s parallel). Frees ~3s of budget for ranking and response generation.

---

## ADR-008: extract-place is a workflow, not an agent

**Date:** 2026-03-05\
**Status:** accepted\
**Context:** extract-place follows a fixed sequence: parse input, validate via Google Places, generate embedding, write to DB. No tool selection or reasoning loop needed.\
**Decision:** Implement extract-place as a sequential async function, not a LangGraph graph. Reserve LangGraph for consult where multi-step reasoning and tool selection are required.\
**Consequences:** Cuts implementation complexity roughly in half. Eliminates graph-specific debugging (state schema, node ordering, conditional edges) for this endpoint.

---

## ADR-007: OpenAI embeddings first, Voyage later

**Date:** 2026-03-04\
**Status:** accepted\
**Context:** Need an embedding provider for place similarity search starting Phase 3.\
**Decision:** Start with OpenAI embeddings (most documented API), swap to Voyage 3.5-lite in Phase 6 as a measurable optimization.\
**Consequences:** Provider abstraction layer must support hot-swapping embedding providers via config.

---

## ADR-006: Python >=3.11,<3.13

**Date:** 2026-03-04\
**Status:** accepted\
**Context:** Need a Python version constraint for pyproject.toml.\
**Decision:** Pin to >=3.11,<3.13. 3.11 minimum for AI library compatibility, upper bound protects against untested 3.13 changes.\
**Consequences:** Must test on both 3.11 and 3.12. Revisit upper bound when 3.13 ecosystem stabilizes.

---

## ADR-005: Single config/models.yaml over split per-provider

**Date:** 2026-03-04\
**Status:** accepted\
**Context:** Need a config structure for the provider abstraction layer.\
**Decision:** Single `config/models.yaml` mapping logical roles to provider + model + params. Only 3-4 models total — one file is readable, swap one line to switch providers.\
**Consequences:** If model count grows significantly, revisit split structure. For now, simplicity wins.

---

## ADR-004: pytest in tests/ over co-located

**Date:** 2026-03-04\
**Status:** accepted\
**Context:** Need to decide where test files live.\
**Decision:** Separate `tests/` directory mirroring `src/` structure. Clean separation, easier to navigate solo.\
**Consequences:** Test discovery configured via pyproject.toml. Import paths must reference the installed package.

---

## ADR-003: Ruff + mypy over black/flake8

**Date:** 2026-03-04\
**Status:** accepted\
**Context:** Need linting and formatting tooling.\
**Decision:** Ruff for lint + format (replaces black, isort, flake8 in one tool). mypy for strict type checking, especially important for Pydantic schema validation.\
**Consequences:** Single `ruff.toml` or `[tool.ruff]` in pyproject.toml. `mypy --strict` as the target.

---

## ADR-002: Hybrid directory structure

**Date:** 2026-03-04\
**Status:** accepted\
**Context:** Need to organize modules inside `src/totoro_ai/`.\
**Decision:** Hybrid layout: `api/` (FastAPI routes), `core/` (domain modules), `providers/` (LLM abstraction), `eval/` (evaluations). Balances domain clarity with clean entry points.\
**Consequences:** Domain modules live under `core/` (intent, extraction, memory, ranking, taste, agent). Cross-cutting concerns like provider abstraction stay at the top level.

---

## ADR-001: src layout over flat layout

**Date:** 2026-03-04\
**Status:** accepted\
**Context:** Need to choose Python package layout.\
**Decision:** src layout (`src/totoro_ai/`) per PEP 621. Prevents accidental local imports during testing.\
**Consequences:** All imports use `totoro_ai.*`. Poetry and pytest configured to find packages under `src/`.
