# Git Conventions

## Comment Character

Git comment char is `;` (not `#`). This is configured in the repo's git config. Use `;` for comments in commit messages and interactive rebase.

## Branch Strategy

```
main          ← stable only, merge when a feature/phase is complete and tested
  └─ dev      ← active development, day-to-day work
       └─ <number>-<feature-name>               (spec-kit feature branch, e.g., 001-intent-parsing)
       └─ feature/<short-description>           (manual feature, e.g., feature/redis-cache)
       └─ fix/<short-description>               (hotfix, e.g., fix/timeout-issue)
```

### Spec-kit Features

- Spec-kit auto-generates numbered branches: `001-feature-name`, `002-another-feature`, etc.
- These are created from `dev` and merged back into `dev` when the feature is complete.
- Numbered naming provides systematic tracking of multiple concurrent features.
- When a feature is fully tested, merge branch into `dev` (squash or merge commit, your call).
- Then merge `dev` into `main` at phase milestones (regular merge, not squash).

### Manual Features & Hotfixes

- Manual features use `feature/<short-description>` pattern.
- Hotfixes use `fix/<short-description>` pattern.
- Both are created from `dev` and merged back into `dev` following the same flow.
- Never push directly to `main`.
- Delete feature/fix branches after merge.

## Commit Message Format

```
type(scope): description #TASK_ID
```

**Types:** `feat`, `fix`, `chore`, `docs`, `refactor`, `test`

**Scopes:** Target the primary affected module/domain:
- `intent` — Intent parsing and extraction
- `providers` — LLM/embedding providers (OpenAI, Anthropic, etc.)
- `ranking` — Recommendation ranking and scoring logic
- `embedding` — Embedding generation and vector operations
- `api` — FastAPI endpoints and request handling
- `db` — Database operations and queries
- `cache` — Redis caching operations
- `config` — Configuration and environment setup
- For changes affecting multiple modules, prioritize the primary one

**Task ID:** ClickUp task ID (e.g., `#abc123`) — optional if no task exists

Examples:
```
feat(intent): add cuisine extraction from free text
fix(providers): handle timeout on OpenAI embedding calls #TASK-456
test(ranking): add integration tests for score normalization
chore(config): update models.yaml with provider mappings #TASK-789
refactor(embedding): simplify vector distance calculations
docs(api): add endpoint documentation for consult endpoint
```

Keep the subject line under 72 characters. Body is optional — use it for non-obvious reasoning.

## Merge Flow

1. Create feature/fix branch from `dev`.
2. Work on branch. Push regularly.
3. When complete, merge branch into `dev` (squash or merge commit — your call per branch).
4. When `dev` is stable and a feature set is complete, merge `dev` into `main`.
5. Never push directly to `main`.
