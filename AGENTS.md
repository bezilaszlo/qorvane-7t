# AGENTS.md

Weather sensor metrics API: FastAPI (async) + SQLAlchemy Core on asyncpg + Postgres, run with Docker Compose. Assumptions and decisions live in `docs/architecture.md`; record new ones there.

FastAPI conventions: follow the skill shipped in the installed package, `fastapi/.agents/skills/fastapi/SKILL.md` (under `.venv/lib/python*/site-packages/`).

## Commands

- `docker compose up --build -d`. Images bake the source with no bind mounts, so code changes need `--build`; `restart` runs the old code. Host port: `API_PORT`.
- `make lint`, `make test` (unit), `make test-integration` (real Postgres via testcontainers, needs Docker), `uv run pre-commit run --all-files`.
- Black-box suite only against a throwaway stack, never the dev or demo DB (its test sensors would leak into the data):
  `API_PORT=8010 docker compose -p bbtest up --build -d && API_BASE_URL=http://localhost:8010 make test-blackbox; docker compose -p bbtest down -v`

## Rules

- Writes use `ConnDep`, reads use `ReadConnDep`. Keep their `scope="function"`: FastAPI's default scope commits after the response is sent, so a 201 could be returned for data that never committed.
- Never interpolate into SQL; pick SQL fragments from fixed mappings.
- Error mapping lives in `app/errors.py`: 422 client input, 503 DB unavailable or timed out, generic 500 otherwise.
- Migrations run only in the `migrate` service, never at app startup, where N workers would race.
- Black-box tests are the API contract: HTTP only, isolated by unique sensor ids and metric names. Don't edit them to make code pass; a change needs a stated reason.
- Test in the right layer: pure logic → unit; DB behavior → integration against real Postgres; API contract → black-box. No fakes or mocks of the DB.
- New behavior starts with a failing test; a bug fix gets a regression test that fails before the fix. No duplicate test cases for the same rule.
- README stays a short, non-technical introduction; technical detail goes to `docs/`.
- Conventional Commits.
