FROM python:3.13.18-slim-trixie
COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1

WORKDIR /app
RUN useradd --system --no-create-home app

COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY static ./static
COPY scripts ./scripts

USER app
EXPOSE 8000
CMD ["sh", "-c", "exec fastapi run app/main.py --host 0.0.0.0 --port 8000 --workers ${WORKERS:-2}"]
