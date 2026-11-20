# Covered: will this expense be covered?

**Repo:** https://github.com/gastoncipolla/spend-policy-engine · runs with `uv sync && uv run covered seed && uv run covered serve` (no API key needed: mock mode).

## Problem
Employees with a corporate card find out an expense was out of policy when finance rejects it, sometimes weeks later. The policy is a PDF nobody reads, and finance reviews everything by hand at month end. Covered answers "will this be covered?" when you spend, and every answer quotes the policy clause behind it.

## Approach
- **A deterministic rules engine is the product.** A pure function checks an expense against five rule types (max amount, prohibited category, pre-approval threshold, per-person period limit, allowed days/hours) and returns `approved`, `needs_approval` or `rejected` with **every** reason.
- **The LLM is used where the problem is language.** It proposes rules from the policy text; code validates them (strict schema, closed category catalog, verbatim quote of the policy, conflicts flagged), and **finance approves each rule** before it is used. Clauses it can't express are flagged for finance, not guessed. Checking an expense never calls the LLM.
- **Roles:** employee, manager, finance. Deny by default, someone else's expense is a 404, nobody approves their own expense, every write records who and when.

## Key decisions and trade-offs
- **Money as integer cents**, never float: exact at limit boundaries.
- **Deterministic engine over "an LLM decides each expense"**: money decisions must be reproducible and auditable, at zero cost per transaction.
- **Period limits with pending expenses:** over the limit with approved spend → rejected; over only because of pending spend → needs approval, with that reason stated.
- **Idempotency-Key on submit**, evaluate + insert in one write transaction: a retry neither duplicates the expense nor spends the limit twice.
- **SQLite, not Postgres:** one command to run, no Docker. Postgres is a change contained in `store/`.
- **Out of scope on purpose:** real login, multi-currency (rejected, never silently converted), taxes, receipt OCR, an ORM.

## How I used AI
- I worked out problem, scope and decisions with Claude (Opus 5.5) in a decision log, dropping two candidate problems whose data I couldn't verify.
- With the spec fixed, agents built it layer by layer with tests green at each stage, and **a different model (Sonnet 5.5) reviewed adversarially**. I reviewed and corrected.
- What went wrong: with 240 tests green, **the first real API call failed**: the schema put the rule type last and the model mixed rule variants. Fixed with a regression test. Lesson: a fake client doesn't test the real API contract.
- **Model choice, measured:** a small eval (`evals/compiler/`: 11 hand-labelled policies, 70 clauses, 2 runs per model). Haiku 5.5 91%, Sonnet 5.5 90%; Haiku costs ~14x less (~USD 0.001 per policy), so it's the default and Sonnet is one env var away. The eval also caught an over-broad rule in my own prompt. Small, self-written sample: stated as such.
- **Ask Covered:** an employee types "dinner with a client last Friday, USD 120"; the LLM only fills in the form (the amount must appear in the text, category from the catalog), the employee confirms, the engine decides. 40/40 on 20 hand-labelled sentences, ~1 s each.
- Process: protected `main`, PRs with three required checks.

## Next steps
Approval chains by amount; SSO; currency per rule with FX rates; per-unit limits (per night, per person); four-eyes on policy activation; Postgres; an append-only audit log; testing the compiler on real company policies.
