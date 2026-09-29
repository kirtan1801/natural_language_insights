FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Dependencies first so code changes don't bust the layer cache.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --all-extras --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev --all-extras

ENV DATABASE_PATH=/app/data/database.db \
    UPLOAD_DIRECTORY=/app/data/uploads
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "natural_language_insights.main:app", "--host", "0.0.0.0", "--port", "8000"]
