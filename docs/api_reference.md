# API Reference

Live endpoints as of Week 2. The full contract for later weeks is in brief
Section 12. OpenAPI docs are always current at `/docs`.

Auth: send `X-API-Key` on every endpoint except `/health/live`. Errors return
`application/problem+json` with fields type, title, status, detail.

## Health and meta

`GET /health/live`

Liveness. No auth. Returns `{"status": "ok"}`.

`GET /health`

Readiness. Checks PostgreSQL and Redis. Returns status ok or degraded plus a
per-dependency list.

```json
{
  "status": "ok",
  "version": "0.1.0",
  "dependencies": [
    {"name": "postgres", "ok": true, "detail": null},
    {"name": "redis", "ok": true, "detail": null}
  ]
}
```

`GET /meta/models`

Registry of model names and versions the system loads. Versions read "pending"
or "not_trained" until the NLP and LLM weeks land.

## Ingestion

`POST /ingestion/csv`

Multipart upload of an official export. Fully working with no credentials.

Form fields:

- `file`: the CSV file (required)
- `profile`: profile id, default `meta_business_suite_posts`. Options:
  `meta_business_suite_posts`, `meta_business_suite_ig_posts`,
  `kaggle_engagement_generic`
- `platform`: override platform when the profile has none (Kaggle)
- `account_external_id`: default account id for exports that omit a page id
- `account_name`: default account display name
- `as_of`: ISO 8601 capture time for the snapshot. Defaults to now. Re-importing
  the same file with the same `as_of` is fully idempotent

Response:

```json
{
  "source": "csv",
  "profile": "meta_business_suite_posts",
  "accounts_upserted": 1,
  "posts_upserted": 2,
  "snapshots_inserted": 2,
  "comments_upserted": 0,
  "rows_skipped": 0,
  "skip_reasons": {}
}
```

Re-uploading the same file inserts zero new posts. Same-instant snapshots
dedupe.

`GET /ingestion/status`

Row counts per table and current sync cursors.

```json
{
  "row_counts": {"accounts": 3, "posts": 120, "post_metric_snapshots": 120, "comments": 210},
  "cursors": []
}
```

`POST /ingestion/run`

Triggers a live connector sync. Meta and YouTube connectors land in Week 3, so
this returns 501 with a clear message until then. Use `/ingestion/csv` today.

## KPIs

Every KPI is either a number or `{"value": null, "reason": "..."}`. A null with a
stable reason means the platform does not expose the field, never a lying zero.
Formulas and reason codes are documented in `docs/models_and_algorithms.md`.
Responses are cached in Redis for 15 minutes; if Redis is down the endpoint still
computes and serves the answer.

`GET /kpi/overview`

Query: `account_id` (required), `window` (default `30d`, forms like `7d`, `48h`,
`12w`), `include_synthetic` (default true).

Headline KPIs for the window plus deltas against the immediately preceding window
of equal length.

```json
{
  "account_id": 1,
  "handle": "cm_demo_ig",
  "platform": "instagram",
  "window": "30d",
  "engagement_rate_basis": "err",
  "followers": {"value": 8200, "basis": "account_latest"},
  "n_posts": 13,
  "posting_frequency_per_week": {"value": 3.03, "reason": null},
  "total_engagement": 3211,
  "avg_engagement_rate": {"value": 4.72, "reason": null},
  "median_engagement_rate": {"value": 4.70, "reason": null},
  "posting_consistency_hours": {"value": 49.8, "reason": null},
  "deltas": {
    "total_engagement_pct": {"value": 12.4, "reason": null},
    "avg_engagement_rate_pct": {"value": 3.1, "reason": null},
    "n_posts_pct": {"value": 8.3, "reason": null}
  },
  "best_post": {"post_id": 31, "engagement_rate": 6.57, "permalink": "..."},
  "worst_post": {"post_id": 34, "engagement_rate": 2.27, "permalink": "..."}
}
```

`engagement_rate_basis` is `err` when reach is exposed, else `erf` (by followers).
`followers.basis` is `snapshot`, `account_latest`, or `unavailable`.

`GET /kpi/timeseries`

Query: `account_id` (required), `metric` (default `err`; also `engagement`,
`likes`, `comments`, `shares`, `saves`, `reach`, `impressions`, `video_views`,
`clicks`), `granularity` (`hour`, `day`, `week`, `month`), `from` and `to` (ISO
8601), `rolling` (optional integer 2..90 adds a trailing rolling-mean series),
`include_synthetic`.

Chart-ready and gap-filled with explicit zeros.

```json
{
  "account_id": 1,
  "metric": "err",
  "granularity": "week",
  "labels": ["2026-06-08", "2026-06-15", "2026-06-22", "2026-06-29", "2026-07-06"],
  "series": [{"name": "engagement_rate_by_reach", "data": [4.08, 4.39, 5.53, 4.41, 3.79]}]
}
```

`GET /kpi/by-platform`

Query: `window` (default `30d`), `include_synthetic`.

Cross-platform comparison. Raw per-platform KPIs plus a z-score of each platform
against its own trailing 90-day baseline, the statistically honest way to answer
"which platform is doing better".

```json
{
  "window": "30d",
  "note": "Raw ER is not comparable across platforms; the z-score is each platform vs its own 90-day baseline.",
  "platforms": [
    {"platform": "instagram", "n_posts": 13, "engagement_rate_basis": "err",
     "avg_engagement_rate": {"value": 4.74, "reason": null},
     "median_engagement_rate": {"value": 4.72, "reason": null},
     "total_engagement": 3211,
     "zscore_vs_90d_baseline": {"value": 0.05, "reason": null}}
  ]
}
```

`GET /kpi/top-posts`

Query: `account_id` (required), `metric` (default `err`), `limit` (1..100, default
10), `window` (optional), `include_synthetic`.

Posts ranked by the chosen metric, each with a full 10-KPI breakdown.

```json
{
  "account_id": 1,
  "metric": "err",
  "count": 3,
  "posts": [
    {"post_id": 31, "published_at": "2026-...", "content_type": "photo",
     "score": 6.57, "score_basis": "err", "engagement": 223,
     "kpis": {"engagement_rate_by_reach": {"value": 6.57, "reason": null}, "...": {}}}
  ]
}
```

Errors: unknown `account_id` returns 404, a bad `window` or `metric` returns 400,
a malformed `from`/`to` returns 422, all as `application/problem+json`.

## Sentiment

Multilingual sentiment across French, English, Arabic, and Tunisian Arabizi.
The Docker image bundles the sentiment stack; the model weights download on the
first request and are cached in a volume (so the first call is slower). Outside
Docker, install the model with `pip install -e ".[nlp]"`. Until the model is
present, endpoints that need it return 503 with an actionable message (language
detection still works without it).

`POST /sentiment/analyze`

Body `{"texts": ["...", "..."]}` (1 to 200 items). Returns per-text language,
sentiment, confidence, and model traceability.

```json
{
  "results": [
    {"text": "3ajbetni barcha", "language": "aeb-latn", "language_confidence": 0.87,
     "language_method": "arabizi_rule", "sentiment": "positive", "score": 0.95,
     "model_name": "cardiffnlp/twitter-xlm-roberta-base-sentiment",
     "model_version": "xlmr-base-multilingual-1.0",
     "needs_arabizi_specialist": true, "emoji_polarity": 0.0}
  ]
}
```

`POST /sentiment/run`

Query `account_id?` and `limit` (1 to 5000). Analyzes stored comments that have
no label yet and writes results to `comment_analyses`. Idempotent: a second run
finds nothing new. Returns `{"analyzed": N, "skipped": 0}`.

`GET /sentiment/summary`

Query `account_id` (required) and `window` (default `30d`). Distribution and
percentages, net sentiment in [-1, 1], a per-language breakdown, a daily trend,
and deltas versus the previous window.

`GET /sentiment/negative-alerts`

Query `account_id` (required), `window` (default `14d`), `limit`. Recent negative
comments plus per-day negative share, with days flagged where the share exceeds
mean + 2 sigma over at least 10 comments.
