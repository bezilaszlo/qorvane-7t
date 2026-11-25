# AGENTS.md

Weather sensor metrics service: REST API that ingests sensor readings and answers min/max/sum/avg over 1–31 day ranges. FastAPI (async) + SQLAlchemy 2 Core on asyncpg + Postgres 17, static Alpine.js UI, Docker Compose.

## Read first

- `docs/design.md`: current design, decisions, guardrails, next steps. Record new decisions here.
- `docs/plan.md`: original plan; its Assumptions section is the API contract.
- FastAPI skill (version-matched, after `uv sync`): `.venv/lib/python3.13/site-packages/fastapi/.agents/skills/fastapi/SKILL.md`. Follow it for endpoints, `Annotated` deps, Pydantic models.

## Map

- `app/api/`: `readings.py` (ingest), `stats.py` (query), `sensors.py`, `health.py`
- `app/db.py`: engine, pool, Postgres timeouts, `ConnDep` / `ReadConnDep`
- `app/errors.py`: all 422/503/500 mapping. `app/ranges.py`: range rules (pure). `app/schemas.py`: models and limits
- `tests/blackbox/`: HTTP contract suite. `tests/unit/`: pure logic and what HTTP can't reach
- `scripts/seed.py`, `perf/` (k6), `static/` (UI), `alembic/` (migrations)

## Commands

- Stack: `docker compose up --build -d` / `docker compose down`. Host port `API_PORT` (default 8000; may be taken, then pick another).
- Images bake the source, no bind mounts: after code changes `up --build`; `restart` runs old code.
- Lint/types: `make lint`. Unit tests: `make test`. All gates: `uv run pre-commit run --all-files`.
- Black-box suite: always against a throwaway stack, never the demo/dev DB:
  `API_PORT=8010 docker compose -p bbtest up --build -d && API_BASE_URL=http://localhost:8010 make test-blackbox; docker compose -p bbtest down -v`
- Seed: `make seed`. Load tests: `make perf-ingest`, `make perf-query` (see `docs/performance.md`).

## Rules

- Async only: `async def` endpoints, every DB call awaited, no blocking I/O on the event loop.
- SQLAlchemy Core, not the ORM. Tables in `app/models.py`. Never interpolate into SQL; pick SQL fragments from fixed mappings.
- Writes use `ConnDep` (transaction, `scope="function"`: commits before the response). Reads use `ReadConnDep` (autocommit). Don't change either scope; a unit test guards commit-before-ack.
- New error cases go through `app/errors.py`: 422 client input, 503 DB unavailable/timeout, generic 500 otherwise (logged, no internals).
- Migrations only via the `migrate` service (`alembic upgrade head`), never in app lifespan. Migrations don't get the app's statement timeout.
- Black-box tests are the contract: HTTP only, never import app code or touch the DB; isolate with unique sensor ids and metric names. Don't edit them to make code pass; a change needs a stated reason (test bug or deliberate contract change recorded in docs).
- New behavior: failing test first, then code. Bug fix: regression test that fails before the fix. Add a test only for a behavior with a credible regression not already covered; no duplicate cases of one rule.
- Docs: README is a short, non-technical introduction. Technical detail, decisions and measurements go to `docs/design.md` / `docs/performance.md`.
- Pinned versions for images and CDN scripts. Config via env, documented in `.env.example`.
- Conventional Commits (`feat|fix|refactor|test|docs|chore|perf|style|build|ci`).
