.PHONY: up down build migrate seed test test-unit test-integration test-local lint fmt shell logs

up:
	docker compose up --build

down:
	docker compose down

build:
	docker compose build

migrate:
	docker compose exec api alembic upgrade head

seed:
	docker compose exec api python -m scripts.seed_dev_data

# Integration tests DROP every table, so they run against a throwaway database,
# never the live app data. The database is created if missing (the leading `-`
# ignores the "already exists" error), and TEST_DATABASE_URL is injected for the
# run. The conftest safety guards refuse any target not named like a test db.
TEST_DB_URL ?= postgresql+psycopg://community_management:community_management@db:5432/community_management_test

# Everything, with coverage. This is the target CI mirrors.
test:
	-docker compose exec db psql -U community_management -d community_management -c "CREATE DATABASE community_management_test"
	docker compose exec -e TEST_DATABASE_URL=$(TEST_DB_URL) api pytest --cov=app/analytics --cov=app/nlp --cov-report=term-missing

# Fast feedback: pure functions only. Integration tests skip themselves without
# TEST_DATABASE_URL, which is why a plain `pytest` run reports skips.
test-unit:
	docker compose exec api pytest -q

# The skipped ones: creates the throwaway database if missing (the leading `-`
# ignores "already exists") and points the suite at it. Nothing here can touch the
# live database; the conftest refuses any target whose name lacks "test".
test-integration:
	-docker compose exec db psql -U community_management -d community_management -c "CREATE DATABASE community_management_test"
	docker compose exec -e TEST_DATABASE_URL=$(TEST_DB_URL) api pytest -q

# Run tests locally without Docker (needs deps installed: pip install -e ".[dev]").
# Point TEST_DATABASE_URL at your own local test database first, e.g.:
#   export TEST_DATABASE_URL=postgresql+psycopg://community_management:community_management@localhost:5432/community_management_test
test-local:
	pytest --cov=app/analytics --cov=app/nlp --cov-report=term-missing

lint:
	ruff check .

fmt:
	ruff format .

shell:
	docker compose exec api bash

logs:
	docker compose logs -f api worker beat
