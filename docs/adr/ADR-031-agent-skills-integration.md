## ADR-031: Agent Skills Integration in Development Workflow

**Date:** 2026-03-12
**Status:** accepted
**Context:** The totoro-ai project uses Claude Code with 2 agent skills installed to enhance development efficiency. Without a documented integration strategy, skills may be invoked at suboptimal workflow stages, wasting tokens or missing optimization opportunities.

**Decision:** Agent skills are scoped to specific workflow stages (from ADR-028) and invoked automatically when task context matches their domain. The mapping is:

| Workflow Step | Active Skills | Activation Trigger |
|---------------|---------------|-------------------|
| **Clarify** | _(none)_ | — |
| **Plan** | _(none)_ | — |
| **Implement** | `fastapi` | Writing/modifying FastAPI routes, schemas, request handlers |
| **Verify** | _(built-in)_ | `poetry run pytest`, `ruff check`, `mypy` |
| **Complete** | `use-railway` | Deployment required, environment config, service provisioning |

**Skill Details:**

- `fastapi` — FastAPI patterns, route design, dependency injection, request/response validation, middleware, OpenAPI schema generation
- `use-railway` — Railway deployment workflows, environment variables, service provisioning, database configuration, build/runtime troubleshooting

**Invocation Rule:** A skill is invoked automatically (without user request) when task context shows the skill domain is directly relevant AND the workflow step matches the table above. Examples:
- Adding a new endpoint (`POST /v1/extract-place`) → `fastapi` invoked in Implement phase
- Configuring Redis cache or PostgreSQL for Railway → `use-railway` invoked in Complete phase
- Running tests → no skill invoked (built-in verification)

**Consequences:**
- Skills reduce implementation time by providing focused guidance on FastAPI patterns and Railway operations
- Skills are available globally and auto-invoked based on task context
- Claude automatically invokes skills based on domain relevance, eliminating manual configuration
- Token efficiency improves through targeted skill use instead of exploratory implementations
- Future additions of skills (e.g., langchain-expert, pgvector-optimization) will extend this table and require ADR update

**Notes:**
- Skills auto-trigger based on code domain, not user prompt keywords
- Both skills follow the same principles as the codebase (see CLAUDE.md, ADR-028)
- If skill guidance conflicts with project standards (CLAUDE.md, architecture.md), project standards take precedence
