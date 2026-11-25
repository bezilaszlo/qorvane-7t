.PHONY: up down test test-blackbox lint

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
