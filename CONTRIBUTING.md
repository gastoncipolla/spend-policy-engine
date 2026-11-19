# Contributing

## Workflow

1. Branch from `main`: `<type>/<short-kebab-description>`, e.g. `feat/approval-chains`, `fix/period-window-dst`.
2. Commit with [Conventional Commits](https://www.conventionalcommits.org/): `<type>(<scope>)?: <summary>`.
3. Open a pull request whose title follows the same format. CI must be green.
4. Squash-merge. The PR title becomes the commit on `main`, so `main` reads as one line per change.

`main` is protected: no direct pushes, no force pushes, and every check below must pass.

## Types

| Type | Use for |
|---|---|
| `feat` | A new capability |
| `fix` | A bug fix |
| `docs` | Documentation only |
| `test` | Tests only |
| `refactor` | Code change with no behavior change |
| `perf` | Performance |
| `ci` | CI, build, Docker |
| `chore` | Maintenance (dependencies, tooling) |

Common scopes: `domain`, `engine`, `compiler`, `store`, `services`, `authz`, `api`, `web`, `cli`, `seed`, `spec`.

## Checks (`.github/workflows/ci.yml`)

- **Branch and PR title conventions**: the rules above.
- **Lint and tests**: `uv run ruff check`, `uv run ruff format --check`, `uv run pytest -q`.
- **Docker build and smoke test**: builds the image, starts it without an API key and checks `/health` and the pages.

Run the same locally before pushing:

```bash
uv run ruff check && uv run ruff format --check && uv run pytest -q
```

GitHub Actions are pinned to commit SHAs (a tag can be moved; a SHA cannot). Dependabot proposes updates weekly.
