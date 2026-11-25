# AGENTS.md

Weather sensor metrics service: REST API ingesting sensor readings, answering min/max/sum/avg over a time range. FastAPI + Postgres 17 + static Alpine.js UI, run via Docker Compose.

Source of truth: `docs/plan.md` (stack, assumptions, API, milestones). Follow it; record deliberate deviations there.

FastAPI skill: https://github.com/fastapi/fastapi/blob/master/fastapi/.agents/skills/fastapi/SKILL.md (official, shipped in the FastAPI repo). Follow it for endpoints, `Annotated` deps, Pydantic models.

## Commands

- Stack: `docker compose up --build -d` / `docker compose down` (`make up`, `make down`)
- Lint/types: `uv run ruff check && uv run ruff format --check && uv run ty check` (`make lint`)
- Unit tests: `uv run pytest tests/unit -q` (`make test`)
- Black-box tests: `uv run pytest tests/blackbox` against the running stack (`API_BASE_URL`)
- All gates: `uv run pre-commit run --all-files`

## Rules

- Async only: `async def` endpoints, no blocking calls on the event loop.
- SQLAlchemy Core, not the ORM. Tables live in `app/models.py`.
- Migrations only via the `migrate` compose service (`alembic upgrade head`), never in app lifespan.
- Black-box tests (`tests/blackbox/`) are the contract: HTTP only, never import app code. Implementation must not edit tests to make them pass; a test change needs a stated reason.
- Red/green: tests first (failing), then implementation. One commit per milestone.
- Conventional Commits (`feat|fix|refactor|test|docs|chore|...`).
- Pinned versions for images and CDN scripts. Config via env (`.env.example`).
