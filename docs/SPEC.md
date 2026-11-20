# Covered — specification (MVP)

> "Will this expense be covered?" Turn a written expense policy into explicit, auditable rules,
> and evaluate every expense against them deterministically, citing the policy clause behind each outcome.

This document is the contract for the MVP. If code and spec disagree, the spec wins until it is changed on purpose.

## 1. Principles

1. **The deterministic engine is the product.** Evaluating an expense never calls an LLM. If the LLM is down, expenses are still evaluated.
2. **The LLM is optional and runs once per policy version**, to propose rules from the policy text. A human (finance) approves every rule before it is used.
3. **Never guess.** Ambiguous clauses are reported as *uncompilable*, unknown categories are validation errors, and an employee without an active policy is an error, never an approval.
4. **Every outcome cites its source**: rule id + the literal policy clause.
5. **Money is integer minor units** (`amount_minor: int`), never float. MVP supports one company currency (USD, 2 decimals); other currencies are a 422.
6. **Auditable**: active policy versions are immutable; each decision stores the policy id + version that produced it.

## 2. Domain model

```
Company       currency = "USD", timezone = "America/Argentina/Buenos_Aires"   (config, not a table)
Category      code, name     closed catalog: meals, ground_transport, lodging, airfare, software,
                             training, entertainment, alcohol, other
Employee      id, name, policy_id
Policy        id, name
PolicyVersion policy_id, version (1..n), text, status: draft | compiling | compile_failed | active | retired,
              compile_error?, compile_meta? (model, prompt_version, input_tokens, output_tokens, latency_ms, cost_usd),
              created_by? (who loaded the text; null for versions created before it was recorded)
Rule          id, policy_id, version, type, params (typed per type), clause (literal quote from text),
              status: proposed | approved | rejected, origin: llm | manual, flags[] (e.g. "conflict")
Uncompilable  id, policy_id, version, clause, reason, categories (list | ["*"]),
              effect: requires_review | informational, status: proposed | confirmed
Expense       id, employee_id, amount_minor, currency, category, merchant, occurred_at (tz-aware),
              justification?, pre_approval_id?, status: approved | pending | rejected, created_at
Decision      expense_id?, employee_id, policy_id, policy_version, outcome, reasons[], warnings[], evaluated_at
              (expense_id is null only for a check; a stored decision always has one, unique per expense)
Reason        rule_id | uncompilable_id, clause, outcome (rejected | needs_approval), message
IdempotencyRecord  actor_id, key, request_hash, response_json, created_at   (unique per (actor_id, key))
```

Expense `status` mirrors the decision outcome (`approved` → approved, `needs_approval` → pending, `rejected` → rejected) and changes only through `resolve` (pending → approved | rejected).

## 3. Rule types (exactly five in the MVP)

Each rule evaluates to `pass`, `needs_approval` or `rejected`, with a human-readable message.

| type | params | semantics |
|---|---|---|
| `max_amount` | `category`, `amount_minor` | `amount > max` → rejected. Equal passes. |
| `prohibited_category` | `category` | category matches → rejected. |
| `pre_approval_threshold` | `amount_minor`, `categories` (list or null = all) | `amount > threshold` and no `pre_approval_id` → needs_approval. With `pre_approval_id` → pass (the MVP trusts the id; verifying it is out of scope). |
| `period_limit` | `category`, `amount_minor`, `period` (`month` \| `week`) | per employee, see §4.3. |
| `time_restriction` | `categories` (list or null), `allowed_weekdays` (0=Mon..6=Sun), `allowed_hours` (`{start:"HH:MM", end:"HH:MM"}` or null), `justification_allows_review: bool` | If `occurred_at` (in company tz) is outside the allowed days/hours: rejected; but if `justification_allows_review` and the expense has a non-empty justification → needs_approval. |

Params are validated with Pydantic discriminated unions (`type` is the discriminator). Amounts > 0, categories must exist in the catalog.

## 4. Engine

### 4.1 Signature

```python
def evaluate(expense: ExpenseInput, policy: CompiledPolicy, history: PeriodHistory, tz: ZoneInfo) -> Decision
```

Pure function: no I/O, no clock (evaluated_at is passed in or set by the caller). `CompiledPolicy` = approved rules + confirmed uncompilable clauses of the active version.

### 4.2 Combining results

- Final outcome precedence: `rejected` > `needs_approval` > `approved`.
- **All** non-pass reasons are returned, including needs_approval reasons when the final outcome is rejected.
- Uncompilable clauses whose `categories` include the expense category (or `*`):
  - `requires_review` → a needs_approval reason citing the clause.
  - `informational` → a warning citing the clause.
- **Uncovered category**: if no approved rule names the expense category explicitly (rules with `categories = null` do not count), or the category is `other` → needs_approval with reason "No rule covers this category".
- No active policy for the employee → error (HTTP 409 `no_active_policy`), never a decision.

### 4.3 Period limit with pending expenses

`history` contains the employee's stored expenses in the same category and period (period computed from `occurred_at` in company tz; month = calendar month, week = ISO week), split into `approved_sum` and `pending_sum`. Rejected expenses and checks (simulations) never count.

```
if approved_sum + amount > limit:                 rejected
elif approved_sum + pending_sum + amount > limit: needs_approval  ("exceeds the limit if pending expenses of X are approved")
else:                                             pass
```

Worked example (limit USD 200/month on ground_transport, plus pre-approval threshold USD 80):
1. Taxi 60 → approved (approved 60).
2. Taxi 90 → needs_approval via threshold (pending 90).
3. Taxi 70 → 60+70=130 ≤ 200 but 60+90+70=220 > 200 → needs_approval citing the pending 90.

## 5. Policy compilation

1. `POST /policies/{id}/versions` creates a `draft` with the text.
2. `POST .../compile`:
   - If status is `compiling` → 409 (one compile at a time per version). Set `compiling` before calling the provider.
   - Provider returns `CompilationResult { rules: [...], uncompilable: [...] }` (structured output; JSON schema generated from the Pydantic models).
   - **Deterministic validation** (never trust the provider):
     - schema valid; amounts > 0; categories in catalog;
     - **each `clause` must be a literal substring of the policy text** (whitespace-normalized). Otherwise the rule is dropped and recorded as uncompilable with reason `clause_not_found_in_text`;
     - conflicts (two rules of the same type for the same category with different params) get `flags: ["conflict"]`.
   - Everything is stored as `proposed` in one transaction; status back to `draft`. On any failure: status `compile_failed` + `compile_error`, nothing partial is stored.
3. Finance reviews: approve/reject/edit rules (`PATCH /rules/{id}`), add manual rules, classify uncompilable clauses (`PATCH /uncompilable/{id}`).
4. `POST .../activate`: 409 if any rule is `proposed` or any uncompilable is not `confirmed`, or any rule with flag `conflict` is approved. On success: previous active version → `retired`, this one → `active` (immutable from now on). Response includes `uncovered_categories`.

### 5.1 Providers

- `AnthropicProvider` (real): Anthropic Python SDK, structured outputs via `output_config.format` (check the SDK docs; do not guess the API). Model from env `COVERED_MODEL` (default `claude-haiku-5-5`; see README "Model choice"). Policy text goes inside `<policy>` tags and is treated as data. Store `prompt_version` constant.
- `MockProvider`: used when `ANTHROPIC_API_KEY` is not set (or `COVERED_PROVIDER=mock`). Returns pre-recorded results from `fixtures/compilations/<sha256 of normalized text>.json` for the sample policies; unknown text → `compile_failed` with a clear "mock mode only supports the sample policies" error. The UI and CLI show which provider is active.

### 5.2 Failures and backoff

- Transport retries are delegated to the SDK: it retries connection errors, 408, 409, 429 and ≥500 with exponential backoff and honors `retry-after`. Configure `max_retries=3`, `timeout=60s`.
- **No application-level retry loop on top of the SDK** (it would multiply attempts: retry amplification).
- Non-retryable: 400/401/403, `stop_reason` `refusal` or `max_tokens`, schema-invalid output → `compile_failed` with the reason.
- Evaluation never depends on the provider.

## 6. Expenses

- `POST /expenses/check` → Decision. Stores nothing, consumes no limit.
- `POST /expenses` (requires header `Idempotency-Key`) → `{expense, decision}`:
  - keys are scoped per authenticated user (the actor who submits): two users may send the same key independently;
  - same key + same request hash → return the stored response (same status code and body);
  - same key + different body → 409 `idempotency_key_reused`;
  - evaluation + insert run in one write transaction (`BEGIN IMMEDIATE` on SQLite) so two concurrent submits cannot both consume the same remaining limit.
- `GET /expenses?employee_id=` → list with decisions.
- `POST /expenses/{id}/resolve {resolution: approved | rejected}` → only from `pending`, else 409.

## 7. API (FastAPI, JSON)

```
GET   /health
GET   /categories
GET   /employees
GET   /policies
POST  /policies                                {name}
POST  /policies/{id}/versions                  {text}
GET   /policies/{id}/versions/{v}              version + rules + uncompilable + uncovered_categories
POST  /policies/{id}/versions/{v}/compile
POST  /policies/{id}/versions/{v}/rules        manual rule (origin=manual, status=approved)
PATCH /rules/{id}                              {status?, params?}   (only on non-active versions)
PATCH /uncompilable/{id}                       {categories, effect} → status confirmed
POST  /policies/{id}/versions/{v}/activate
POST  /expenses/check
POST  /expenses                                header Idempotency-Key
GET   /expenses?employee_id=
POST  /expenses/{id}/resolve
```

Errors: JSON `{error: code, message}` with consistent codes (`validation_error`, `not_found`, `no_active_policy`, `version_immutable`, `compile_in_progress`, `activation_blocked`, `idempotency_key_reused`, `invalid_transition`).

## 8. CLI (Typer) and pages

- CLI `covered` wraps the same services (not HTTP): `covered serve`, `covered seed`, `covered check --employee ana --amount 80.00 --category meals --at 2026-11-21T21:00`, `covered submit ...`, `covered policy show|compile|activate`. Amounts are typed as decimals by humans and converted to minor units at the edge with `Decimal`, never float.
- Pages (Jinja2, server-rendered, plain CSS, no build step):
  - `/` → links to both views and shows the active provider (mock/real).
  - `/employee` → pick employee, "Will this be covered?" form (check) and "Submit" button, outcome with every reason and its quoted clause, expense history.
  - `/finance` → policy text side by side with proposed rules (each rule next to its clause), approve/reject, classify uncompilable clauses, activate, pending expenses to resolve.
  - Clarity over polish: readable, consistent colors for approved/needs_approval/rejected.

## 9. Seed data (fictional, no real people or companies)

- Policies: "Sales" and "Engineering", each with one active version compiled from `fixtures/policies/sales.md` and `fixtures/policies/engineering.md` via the mock fixtures.
- Employees: Ana, Bruno (Sales), Carla, Diego (Engineering).
- The sample policies must contain clauses for all five rule types plus these uncompilable cases: "economy class unless the flight is longer than 8 hours" (requires_review, airfare), "client meals require a reasonable business justification" (requires_review or informational — pick and document), "personal expenses are not reimbursable" (informational, *), "prefer partner hotels" (informational, lodging), and "hotel stays up to USD X per night" (requires_review, lodging): a per-unit limit (per night, per person, per km...) is not a per-expense `max_amount`, because one expense can cover several units.

## 10. Observability

Structured JSON logs (stdlib `logging`): one event per compile (provider, model, prompt_version, tokens, latency_ms, cost_usd, outcome) and per decision (employee, policy version, outcome, rule ids). No PII beyond the fictional employee id.

## 11. Code layout

```
src/covered/
  domain/     models (Pydantic), money, categories, errors
  engine/     pure evaluation: one module per rule type + combine
  compiler/   schema, providers (anthropic, mock), validation
  store/      SQLite repository (stdlib sqlite3), migrations as plain SQL
  services/   use cases: policies, expenses (transactions live here)
  api/        FastAPI app and routers
  web/        page routes + templates
  cli/        Typer app
tests/        unit (engine, compiler validation, money) + API tests (TestClient)
```

## 12a. Roles, permissions and audit

Roles: `employee`, `manager`, `finance`. A user can have several roles (a manager also spends). Users have `manager_id` (their own manager) and a policy (via `policy_id`). A manager's team = users whose `manager_id` is that manager.

Identity (no login): each seeded user has a fixed demo token sent as `Authorization: Bearer <token>`. `covered seed` prints the tokens and they are documented as demo-only. Missing or unknown token → 401 `unauthenticated`. The CLI takes `--as <user>`; the pages have an "act as" selector (cookie) that maps to the same tokens.

Security principles (enforced in the service layer, never only in the UI):
1. **Deny by default**: an action not explicitly allowed is refused.
2. **Object-level authorization**: access is checked against the specific resource, not only the role. Asking for an expense you may not see → 404 `not_found` (do not reveal it exists).
3. **Separation of duties**: nobody resolves their own expense, finance included (→ 403 `forbidden`, message explains why).
4. **Every write records who and when**: policy version creation (`created_by`, `created_at`), rule review (`reviewed_by`, `reviewed_at`), uncompilable classification, activation (`activated_by`, `activated_at`), expense resolution (`resolved_by`, `resolved_at`).

Permission matrix:

| Action | employee | manager | finance |
|---|---|---|---|
| Check / submit expense | own only (`employee_id` must be the caller) | own only | own only |
| List / get expenses | own | own + team | all |
| Resolve pending expense | no | team members', never own | any, never own |
| Read policy / versions | own policy, read-only | own policy, read-only | all |
| Create policy/version, compile, review rules, classify, activate | no | no | yes |
| List employees | self | self + team | all |

Demo users (fictional): `ana` (employee, Sales, manager `bruno`), `bruno` (employee + manager, Sales, manager `fede`), `carla` (employee, Engineering, manager `diego`), `diego` (employee + manager, Engineering, manager `fede`), `fede` and `gabi` (employee + finance, Engineering policy, no manager; two finance users so each one's own pending expenses can be resolved by the other).

Errors: 401 `unauthenticated`, 403 `forbidden`, 404 `not_found` for hidden resources.

CSRF: page writes use a cookie, so the cookie is `SameSite=Lax` and a middleware rejects unsafe requests that the browser marks as cross-site (`Sec-Fetch-Site`, falling back to `Origin`). Bearer-authenticated API calls are not affected.

## 12b. Robustness additions

- **Request id**: every request gets an id (incoming `X-Request-ID` if valid, else generated), returned in the `X-Request-ID` response header and included in every log line for that request.
- **Catch-all error handler**: unexpected exceptions return 500 `{error: "internal_error", message, request_id}` in the standard envelope, and are logged with the stack trace.
- **Stale compile lock**: a version stuck in `compiling` for longer than the provider's worst case (timeout × (retries + 1) + margin, e.g. 5 minutes, from `compiling_since`) can be compiled again; the stale lock is taken over and logged.

## 12. Definition of done (MVP)

- `uv run pytest` green; `uv run ruff check` and `uv run ruff format --check` clean.
- Engine tests cover every rule type including boundaries (equal to the limit passes), combination precedence, the period-limit worked example, uncovered category, uncompilable effects, timezone edge (expense at 23:30 local on a Sunday).
- Compiler tests: hallucinated clause dropped, unknown category rejected, conflict flagged, failure leaves nothing partial.
- API tests: idempotency (replay + reuse with different body), activation blocked, immutable active version, resolve transitions, no active policy.
- From a clean clone: `uv sync && uv run covered seed && uv run covered serve` works without an API key, and both pages render.
- No secrets, real personal data or recruiter/company-internal data in the repo. `.env` is gitignored; `.env.example` documents variables.
