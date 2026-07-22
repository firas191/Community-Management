# Community Management

[![CI](https://github.com/firas191/Community-Management/actions/workflows/ci.yml/badge.svg)](https://github.com/firas191/Community-Management/actions/workflows/ci.yml)

The data and analytics side of a social-media community-management app. It ingests
posts and comments, computes engagement KPIs, scores sentiment in French, English,
Arabic and Tunisian Arabizi, and turns an account's history into posting
recommendations. A free LLM gateway and a grounded analyst agent are the last two
pieces of the roadmap.

It's built one week at a time from the project brief. Everything runs on real data
and has tests.

## Progress

**Week 1 — skeleton.** Docker Compose (api, worker, beat, Postgres, Redis), the
Postgres schema and Alembic migrations, config, a CSV importer, and synthetic
fixtures for local development. None of this needs an API key; you can bring the
stack up and import a CSV with no credentials.

**Week 2 — KPI engine.** Post- and account-level metrics written as pure functions,
each checked against a hand-worked example. A rate with a missing or zero
denominator returns `null` and a reason code, never a misleading `0`. There's
time-bucketed history (hour/day/week/month, gaps filled, rolling means),
cross-platform z-scores, and four endpoints under `/kpi`. Responses are cached in
Redis for 15 minutes, but the numbers never depend on the cache being up.

```bash
curl -H "X-API-Key: change-me" "localhost:8000/kpi/overview?account_id=1&window=90d"
```

**Week 3 — sentiment.** Text is cleaned, its language is detected (with a
hand-written rule layer for Tunisian Arabizi, the hard case generic detectors get
wrong), and then classified by a multilingual model. The model sits behind an
interface so the pipeline is testable without downloading a gigabyte of weights.
The same week added live connectors: a YouTube Data API v3 connector for public
channels (just needs an API key) and a Meta Graph connector for Facebook Pages,
both feeding a cursor-based sync that ingests incrementally and keeps the raw
payloads. `POST /ingestion/run` triggers a sync; a Celery job also runs it every
30 minutes.

**Week 4 — Arabizi model.** A fine-tune of the sentiment model on the TUNIZI
corpus, trained on a free Colab/Kaggle GPU (script and notebook included). When
`ARABIZI_MODEL` points at the trained model, Arabizi comments route to it and
everything else stays on the base model; the interface doesn't change either way.
The held-out accuracy and per-language numbers are in `docs/models_and_algorithms.md`.

**Week 5 — recommendations.** Best time to post (day and hour, in Tunis local
time), best content type, and best hashtags. Each pick comes with its evidence:
how many posts it's based on, how it compares to the account's own average, and a
confidence tier. A single lucky post can't top the ranking — thin slots are pulled
back toward the average — and if there isn't enough data the engine says so instead
of guessing. Results are saved to the `recommendations` table.

```bash
curl -H "X-API-Key: change-me" -X POST \
  "localhost:8000/recommendations/best-time?account_id=1&window=90d"
```

## Running it

```bash
cp .env.example .env         # the defaults work for a local run
docker compose up --build    # api:8000, worker, beat, postgres, redis
```

Then, in another shell:

```bash
docker compose exec api alembic upgrade head   # migrations
make seed                                       # synthetic demo data
curl -H "X-API-Key: change-me" localhost:8000/health
```

To load a real Meta Business Suite CSV export:

```bash
curl -H "X-API-Key: change-me" \
  -F "file=@export.csv" \
  -F "profile=meta_business_suite_posts" \
  localhost:8000/ingestion/csv
```

API docs are at http://localhost:8000/docs.

## Make targets

```bash
make up       # docker compose up --build
make down     # stop the stack
make migrate  # alembic upgrade head (in the api container)
make seed     # load synthetic demo data
make test     # pytest
make lint     # ruff check
make fmt      # ruff format
```

## Layout

```
app/            FastAPI service: config, core, models, schemas, routes
app/analytics   KPI formulas, aggregation, recommendations
app/nlp         preprocessing, language routing, sentiment, training
app/ingestion   connectors, normalizer, CSV importer, synthetic fixtures
config/         constants and CSV column-mapping profiles
alembic/        migrations
tests/          pytest suite, mirrors app/
docs/           architecture, data dictionary, models and algorithms
```

## Data

The plan is to stay on real data without needing anyone's private account. Public
YouTube is the main live source, a self-owned Meta test page proves the Meta
connector, Kaggle exports exercise the CSV path, and TUNIZI trains the Arabizi
model. Reach and impressions aren't public on those sources, so any reach-based KPI
returns null with a reason rather than a made-up number.

That last point is the rule the whole project follows: when something can't be
computed honestly, say why instead of showing a zero. Recommendations carry their
sample size and confidence, sentiment labels carry the model that produced them,
and counts are stored as timestamped snapshots rather than overwritten.

See `DECISIONS.md` for the choices made along the way and `docs/` for the details.
