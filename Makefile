.PHONY: up down build migrate seed test lint fmt shell logs

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

test:
	-docker compose exec db psql -U community_management -d community_management -c "CREATE DATABASE community_management_test"
	docker compose exec -e TEST_DATABASE_URL=$(TEST_DB_URL) api pytest --cov=app/analytics --cov=app/nlp --cov-report=term-missing

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
