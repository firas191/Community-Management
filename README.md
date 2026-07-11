# Community Management

<!-- Replace OWNER with your GitHub username or org once the repo is pushed. -->
[![CI](https://github.com/OWNER/community-management/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/community-management/actions/workflows/ci.yml)

Intelligent Community Management Analytics Engine. The intelligence layer of a
social media community management application. Multilingual sentiment (French,
English, Arabic, Tunisian Arabizi), KPI and recommendation engines, a free-tier
multi-provider LLM gateway, and a grounded analyst agent.

This repository is the IA / Data and Analytics module. It is built in the
8-week roadmap order from the project brief. Every module ships with real data
paths, tests, and documentation.

## Status

Week 1 delivered: repository, Docker Compose, PostgreSQL schema and migration,
config, a working CSV importer, synthetic dev fixtures, and health plus
ingestion endpoints. The stack runs with no external API key. The CSV import
path and seed fixtures need no credentials.

Week 2 delivered: the KPI engine. Pure, unit-tested formulas for all post-level
and account-level KPIs with null-with-reason guards, temporal aggregation
(hour/day/week/month, gap-filled, rolling means), cross-platform z-scores, and
four endpoints under `/kpi` (overview, timeseries, by-platform, top-posts) with
15-minute Redis caching that degrades gracefully. Formulas are documented in
`docs/models_and_algorithms.md`.

Try it after seeding:

```bash
curl -H "X-API-Key: change-me" \
  "localhost:8000/kpi/overview?account_id=1&window=90d"
```

## Quick start

```bash
cp .env.example .env         # defaults work as-is for local run
docker compose up --build    # api:8000, worker, beat, postgres, redis
```

Then, in another shell:

```bash
docker compose exec api alembic upgrade head   # apply migrations
make seed                                       # load synthetic dev fixtures
curl -H "X-API-Key: change-me" localhost:8000/health
```

Import a real Meta Business Suite CSV export:

```bash
curl -H "X-API-Key: change-me" \
  -F "file=@export.csv" \
  -F "profile=meta_business_suite_posts" \
  localhost:8000/ingestion/csv
```

OpenAPI docs are at http://localhost:8000/docs.

## Commands

```bash
make up          # docker compose up --build
make down        # stop the stack
make migrate     # alembic upgrade head (inside the api container)
make seed        # load synthetic dev fixtures
make test        # run the pytest suite
make lint        # ruff check
make fmt         # ruff format
```

## Layout

```
app/        FastAPI service: config, core, models, schemas, api routes
app/ingestion   connector protocol, normalizer, CSV importer, synthetic fixtures
config/     constants and CSV column-mapping profiles (config over hardcoding)
alembic/    migrations
tests/      pytest suite, mirrors app/
docs/       architecture, data dictionary, models and algorithms
scripts/    seed and backfill utilities
```

## Data strategy

The default plan needs no company access and stays 100% real. Public YouTube is
the primary live source (added Week 3). A self-owned Meta test page proves the
Meta connector. Kaggle datasets stress-test the KPI code through the CSV
importer. TUNIZI trains the Arabizi sentiment model. Reach and impressions are
owner-private on public sources, so reach-based KPIs return null with a reason.

## Principle

Honesty over false completeness. Null with a reason instead of a lying zero.
Evidence (n, lift, confidence) on every recommendation. Model name and version
on every sentiment label. Snapshots instead of overwritten counters.

See `DECISIONS.md` for open-detail choices and `docs/` for full documentation.
