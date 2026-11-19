# Covered

"Will this expense be covered?" Covered turns a written expense policy into explicit rules that
finance approves, then checks every expense against them with a deterministic engine. Each outcome
quotes the policy clause behind it. An LLM is used only once per policy version, to propose rules;
checking an expense never calls it.

The contract is [`docs/SPEC.md`](docs/SPEC.md).

## Quickstart

No API key is needed: without one, Covered uses a mock compiler that returns hand-written results for
the two sample policies.

```bash
uv sync
uv run covered seed     # reset ./data/covered.db: Sales + Engineering policies, 4 employees
uv run covered serve    # http://127.0.0.1:8000
```

Then open:

- <http://127.0.0.1:8000/>: home page; shows which compiler is active (mock or real).
- <http://127.0.0.1:8000/employee>: check an expense ("Will this be covered?"), submit it, and see your history.
- <http://127.0.0.1:8000/finance>: the policy text next to its rules, rule review, version activation and pending expenses.
- <http://127.0.0.1:8000/docs>: the JSON API (OpenAPI).

Demo employees: `ana` and `bruno` (Sales), `carla` and `diego` (Engineering). The sample policies are
in `fixtures/policies/` and belong to a fictional company.

## CLI

The CLI calls the same services as the API directly, not over HTTP. Amounts are decimals
(`95.50`). A time with no UTC offset is read in company time (America/Argentina/Buenos_Aires).

```bash
# Check only: nothing is stored
uv run covered check --employee ana --amount 95.50 --category meals --at 2026-11-22T23:30

# Submit: stores the expense; a new idempotency key is generated unless you pass --key
uv run covered submit --employee ana --amount 60 --category ground_transport --at 2026-11-03T10:00
uv run covered submit --employee ana --amount 90 --category ground_transport --key taxi-2

uv run covered policy show                 # list the policies
uv run covered policy show sales           # rules, uncompilable clauses, uncovered categories
uv run covered policy compile sales -v 2   # compile a draft version
uv run covered policy activate sales -v 2

uv run covered expenses list --status pending
uv run covered expenses resolve 2 approved
```

Run `uv run covered --help` to see every option.

## Using a real LLM

Copy `.env.example` to `.env`, set `ANTHROPIC_API_KEY`, and export the variables before you start
the server (Covered does not read `.env` by itself):

```bash
cp .env.example .env    # then edit it
set -a; source .env; set +a
uv run covered serve
```

| Variable | Meaning |
|---|---|
| `ANTHROPIC_API_KEY` | When it is set, policies are compiled by the Anthropic API. |
| `COVERED_PROVIDER` | `mock` or `anthropic`. Default: `anthropic` if a key is set, otherwise `mock`. |
| `COVERED_MODEL` | Model used for compiling (default `claude-sonnet-5-5`). |
| `COVERED_DB` | SQLite file (default `./data/covered.db`). |

`covered seed` always uses the mock, so the demo data is the same with or without a key. To
compile your own text, create a new version on the finance page (or with `POST
/policies/{id}/versions`) and compile it. The mock only knows the two sample texts.

The server writes one JSON log line per compile and per decision to stderr.

## Tests

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
```

The tests never call the real API: they use the mock provider or a fake client.

## Layout

```
src/covered/
  domain/     Pydantic models, money (int minor units), categories, errors
  engine/     pure evaluation: one module per rule type, plus combine and period windows
  compiler/   output schema, providers (Anthropic, mock), deterministic validation
  store/      SQLite (stdlib sqlite3), SQL migrations, repositories
  services/   use cases and transactions; compiler adapter, seed
  api/        FastAPI app and JSON routes
  web/        page routes, Jinja2 templates, CSS
  cli/        Typer app
fixtures/     sample policies and hand-written mock compilations
tests/        domain, engine, compiler, store, services, api, web, cli, integration
```
