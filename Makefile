.PHONY: up down test test-blackbox lint seed perf-ingest perf-query

SEED_ARGS ?= --sensors 10 --days 30

up:
	docker compose up --build -d

down:
	docker compose down

test:
	uv run pytest tests/unit -q

test-blackbox:
	uv run pytest tests/blackbox -q

lint:
	uv run ruff check && uv run ruff format --check && uv run ty check

seed:
	docker compose --profile tools run --rm seed $(SEED_ARGS)

perf-ingest:
	docker compose --profile perf run --rm k6 run /perf/ingest.js

perf-query:
	docker compose --profile perf run --rm k6 run /perf/query.js
