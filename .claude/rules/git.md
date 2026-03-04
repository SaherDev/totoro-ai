# Git Conventions

## Comment Character

Git comment char is `;` (not `#`). This is configured in the repo's git config. Use `;` for comments in commit messages and interactive rebase.

## Branches

- `main` — stable only. Merged when something is complete.
- `dev` — active development, day-to-day work.
- Feature branches from `dev`: `feature/<phase>-<short-description>` (e.g., `feature/p1-intent-parsing`)
- Bugfix branches: `fix/<short-description>`

## Commit Format

```
type(scope): description #TASK_ID
```

Include the ClickUp task ID. If no task, omit it.

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `ci`
Scope: module or area affected (e.g., `intent`, `api`, `providers`, `config`)

Examples:
```
feat(intent): add cuisine extraction from free text #abc123
fix(providers): handle timeout on OpenAI embedding calls #def456
test(ranking): add integration tests for score normalization
chore(config): add models.yaml with initial provider mappings
```

Keep the subject line under 72 characters. Body is optional — use it for non-obvious "why".

## Merge Flow

1. Create feature/fix branch from `dev`.
2. Work on branch. Push regularly.
3. When complete, merge branch into `dev` (squash or merge commit — your call per branch).
4. When `dev` is stable and a feature set is complete, merge `dev` into `main`.
5. Never push directly to `main`.
