# Architecture

Community Management is the intelligence layer of a community management application. It is
one FastAPI service backed by PostgreSQL and Redis, with Celery for scheduled
work. This document describes the shape delivered in Week 1 and how later weeks
attach to it.

## Services

The stack runs as five containers under Docker Compose.

The `api` container serves the REST API on port 8000 and self-documents at
`/docs`. The `worker` and `beat` containers run Celery. The `db` container is
PostgreSQL 16 with the pgvector extension. The `redis` container is Redis 7.

PostgreSQL is the single source of truth. Redis has three jobs: cache for KPI
and LLM responses, token buckets for free-tier rate limits, and the Celery
broker and result backend.

## Request path

A client sends REST requests with an `X-API-Key` header. Health liveness is the
one exception and needs no key so orchestrators can probe it. Errors return
`application/problem+json` per RFC 7807 with a stable shape of type, title,
status, and detail.

## Data path

Data enters through one of three sources: the Meta Graph API connector, the
YouTube Data API connector, or the CSV importer. Week 1 ships the CSV importer
and the synthetic fixture generator. The two live connectors land in Week 3.

Every source produces the same unified records defined in
`app/ingestion/records.py`. The normalizer in `app/ingestion/normalizer.py`
takes those records, extracts hashtags, maps content types, hashes author ids,
and upserts into PostgreSQL. Posts, accounts, and comments upsert with
`ON CONFLICT DO UPDATE`. Metric snapshots insert with `ON CONFLICT DO NOTHING`
because a snapshot at a given instant is immutable. Re-running any ingestion job
inserts zero duplicates.

## Storage design

Two decisions drive the schema. First, engagement is stored as append-only
snapshots in `post_metric_snapshots`, not as mutable counters. Engagement grows
over time, so snapshots make growth curves, engagement velocity, and anomaly
detection possible later. Second, author ids are never stored raw. The
`author_hash` column holds a SHA-256 of the platform author id, which is GDPR
friendly by construction.

Missing platform metrics are stored as NULL, never 0. Public YouTube hides reach
and impressions, so reach-based KPIs will return null with a reason instead of a
misleading zero.

## Engines

Four engines sit on top of the data.

**analytics** holds the pure KPI formulas and temporal rollups (Week 2) and the
recommendation engine for best time, content type and hashtags, ranked with
shrinkage and reported with evidence (Week 5). The layering is strict: `kpi.py`
and `recommend.py` are pure functions, `aggregation.py` is pure pandas, and only
`service.py` and `recommend_service.py` touch the database.

**nlp** handles preprocessing, language routing with the Tunisian Arabizi rule
layer, multilingual sentiment behind an injectable backend (Week 3), the
fine-tuned Arabizi model routed to for `aeb-latn` text (Week 4), and topic
clustering with the same injectable-backend pattern (Week 8).

**llm** is a LiteLLM multi-provider gateway with failover across the free tiers,
response caching, and one `llm_calls` row per attempt including the provider's
error message (Week 6).

**agent** is a LangGraph think/act loop whose tools are the tested analytics
functions above, read-only and bounded, with the full tool trace persisted to
`agent_runs` (Week 7).

Heavy or conflicting dependencies are isolated as optional extras rather than
forced into the image: `nlp` and `llm` and `agent` are installed, while `train`
(fine-tuning) and `topics` (BERTopic, which caps numpy below the analytics pin)
are not. Every module behind a missing extra answers 503 with an install hint
instead of failing obscurely, so the stack always boots.

## Configuration

No module reads the environment directly. `app/config.py` declares every
variable with a typed default. Model names, provider order, content-type maps,
and CSV column profiles live in `config/`, never inline. Free-tier catalogs and
platform field names change often, so isolating them as data keeps logic stable.

## Timezone policy

Timestamps are stored in UTC. Bucketing for KPIs and charts uses Africa/Tunis.
CSV exports usually carry naive local time, so the importer localizes naive
values to Africa/Tunis and converts to UTC before storage.
