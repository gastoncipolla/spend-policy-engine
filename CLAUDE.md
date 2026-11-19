# Covered — instructions for coding agents

Read `docs/SPEC.md` first. It is the contract; do not change behavior that contradicts it. If something in the spec is ambiguous or wrong, pick the most conservative option, leave a `# SPEC-QUESTION:` comment, and list it in your final report.

## Rules
- Code, comments, identifiers, commit messages and docs: English.
- Python 3.13, managed with uv. Run things with `uv run ...`. Add dependencies only if truly needed, and report them.
- Money is `int` minor units. Never use `float` for money. Parse human input with `Decimal`.
- The engine (`src/covered/engine/`) is pure: no I/O, no clock, no randomness, no LLM.
- Keep modules small and readable: the code will be walked through on video and defended line by line.
- Tests first or alongside: every behavior in the spec has a test. `uv run pytest`, `uv run ruff check`, `uv run ruff format --check` must pass before you finish.
- Never make real calls to the Anthropic API (there is no key on this machine). Use the mock provider or a fake client in tests.
- For the Anthropic SDK (structured outputs, errors, retries), do not guess the API: read the docs in the `claude-api` skill or the official SDK repository.
- Public repo: no secrets, no real personal data, no references to any recruiting process or company. Sample data is fictional.
- Commit in small, meaningful steps with clear messages. Never push.
