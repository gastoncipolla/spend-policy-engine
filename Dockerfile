# Covered: API + pages. Runs in mock mode unless ANTHROPIC_API_KEY is set.
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.3 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    COVERED_DB=/app/data/covered.db

# Dependencies first, so code changes do not reinstall them.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY README.md ./
COPY src ./src
COPY fixtures ./fixtures
RUN uv sync --frozen --no-dev

RUN useradd --create-home app && mkdir -p /app/data && chown app /app/data
USER app

EXPOSE 8000
# Seed demo data on start, then serve on all interfaces inside the container.
CMD ["sh", "-c", "uv run --no-sync covered seed && uv run --no-sync covered serve --host 0.0.0.0 --port 8000"]
