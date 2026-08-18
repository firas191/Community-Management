# Community Management

[![CI](https://github.com/firas191/Community-Management/actions/workflows/ci.yml/badge.svg)](https://github.com/firas191/Community-Management/actions/workflows/ci.yml)

The data and analytics engine behind a social media community management app.

It ingests a brand's posts and comments, computes engagement KPIs, reads comment
sentiment in French, English, Arabic and Tunisian Arabizi, turns that history into
posting recommendations, and answers plain questions about all of it with an agent
that can only quote real numbers.

Everything runs with `docker compose up`. It works on live public data, not mock
data: 221 posts and 1,849 comments from two real YouTube channels plus synthetic
demo accounts. 226 tests, ruff clean, CI green.

The interesting part is the Tunisian Arabizi handling. Generic tools choke on
dialect written in Latin letters and digits ("3ajbetni barcha", "ya3tik sa7a").
This system detects that register with a rule layer and classifies it with a model
fine-tuned on the TUNIZI corpus.

---

## What it does

**Ingests** from the YouTube Data API, the Meta Graph API, and CSV exports.
Incremental by cursor, idempotent on re-run, with every raw payload archived for
30 days.

**Measures** eleven post-level and six account-level KPIs. When a platform hides a
field (public YouTube does not expose reach), the KPI returns null with a reason
code instead of a misleading zero.

**Reads comments** across four registers. Language routing handles Arabizi with a
deterministic rule layer, then sentiment is classified by a multilingual model, or
by the fine-tuned Arabizi specialist for `aeb-latn` text.

**Recommends** when to post, what format to use, and which hashtags work. Every
recommendation carries its sample size, its lift over the account's own average,
and a confidence tier.

**Writes** caption options through a gateway that fails over across five free LLM
providers.

**Answers questions** with an agent whose tools are the tested analytics functions
above, read-only, with the full reasoning trace stored.

---

## Quick start

```bash
cp .env.example .env         # defaults work as-is for a local run
docker compose up --build    # api:8000, worker, beat, postgres, redis
```

In another shell:

```bash
docker compose exec api alembic upgrade head   # create the schema
make seed                                       # load synthetic demo data
curl -H "X-API-Key: change-me" localhost:8000/health
```

Interactive API docs: http://localhost:8000/docs

Every endpoint except `/health/live` needs the `X-API-Key` header. The default is
`change-me`, set by `API_KEY` in `.env`. No external API key is required to bring
the stack up, import a CSV, or explore the seeded data.

---

## How each part works

### Ingesting data

Three paths in, all landing in the same normalized tables.

**Live connectors.** Set credentials in `.env` and trigger a sync:

```bash
curl -H "X-API-Key: change-me" -F "connector=youtube" localhost:8000/ingestion/run
```

YouTube needs only `YOUTUBE_API_KEY` and `YOUTUBE_CHANNEL_IDS`, because public
channels require no OAuth. Meta needs `META_PAGE_ACCESS_TOKEN` and `META_PAGE_IDS`.
Each account keeps a cursor, so a run fetches only what is new, and a Celery job
repeats it every 30 minutes. Re-running never duplicates: writes are upserts on
natural keys.

**CSV import** for official exports, with column mapping defined as config:

```bash
curl -H "X-API-Key: change-me" \
  -F "file=@export.csv" \
  -F "profile=meta_business_suite_posts" \
  localhost:8000/ingestion/csv
```

**Synthetic fixtures** via `make seed`, flagged `is_synthetic` so they are never
presented as real.

Check what is stored with `GET /ingestion/status`.

### Measuring performance

```bash
curl -H "X-API-Key: change-me" \
  "localhost:8000/kpi/overview?account_id=1&window=90d"
```

Windows are strings like `7d`, `48h`, `12w`. Four endpoints cover headline KPIs
with deltas, any metric over time (gap-filled and chart-ready), a cross-platform
comparison, and ranked top posts.

Two behaviours to expect:

- A KPI can come back as `{"value": null, "reason": "reach_unavailable"}`. That is
  correct: the platform does not expose the field, and a zero would lie.
- `engagement_rate_basis` tells you whether a rate is by reach (`err`) or by
  followers (`erf`). Public YouTube has no reach, so it uses `erf` rather than
  returning a column of nulls.

Responses cache in Redis for 15 minutes. If Redis is down the endpoint still
computes and serves the answer.

### Reading sentiment

Run the batch job over stored comments, then read the rollups:

```bash
curl -H "X-API-Key: change-me" -X POST "localhost:8000/sentiment/run"
curl -H "X-API-Key: change-me" "localhost:8000/sentiment/summary?account_id=1&window=90d"
```

The job only analyzes comments with no label yet, so it is safe to re-run. The
first call downloads the model (about 1 GB) into a Docker volume, so it is slow
once and fast afterwards.

Classify text directly to see the routing:

```bash
curl -H "X-API-Key: change-me" -H "Content-Type: application/json" \
  -X POST localhost:8000/sentiment/analyze \
  -d '{"texts":["3ajbetni barcha el video ya3tik sa7a","merci beaucoup"]}'
```

The first returns `language: aeb-latn` with `language_method: arabizi_rule`. Every
label records the model name and version that produced it.

**Using the fine-tuned Arabizi model.** Train it with
`notebooks/finetune_tunizi.ipynb` on a free Kaggle or Colab GPU (a few minutes),
put the result in `models/arabizi/`, then set:

```
ARABIZI_MODEL=/models/arabizi
```

`docker compose up -d` and Arabizi comments route to it, tagged
`tunizi-arabizi-1.0`. Leave the variable empty and they fall back to the
multilingual model, flagged `needs_arabizi_specialist` so a provisional label is
never mistaken for a final one. To re-label comments that already have a label,
delete their rows first:

```sql
DELETE FROM comment_analyses WHERE language = 'aeb-latn';
```

### Getting recommendations

```bash
curl -H "X-API-Key: change-me" -X POST \
  "localhost:8000/recommendations/all?account_id=1&window=90d"
```

Each item comes with `n`, `lift` and `confidence`. Ranking is shrinkage-adjusted,
so a slot with one lucky post cannot outrank a well-sampled one; the raw mean is
reported alongside so nothing is hidden. Times are bucketed in Africa/Tunis.
Not enough data returns a `reason` rather than a guess. Results are stored in the
`recommendations` table as an audit trail.

### Generating captions

Add any provider key to `.env` (Groq, Gemini, OpenRouter or NVIDIA), then:

```bash
curl -H "X-API-Key: change-me" -X POST localhost:8000/llm/generate \
  -H "Content-Type: application/json" \
  -d '{"brief":"weekend promo on grilled sandwiches","account_id":1,"n":3}'
```

Passing `account_id` feeds that account's recent posts to the model as a
brand-voice reference. `GET /llm/providers` shows which providers are configured
and the resulting failover chain.

The gateway tries models in order and returns the first that answers, skipping any
whose key is unset. Every attempt is logged to `llm_calls` with tokens, latency,
fallback depth and the provider's error message when it failed:

```sql
SELECT provider, model, status, fallback_depth, left(error, 60)
FROM llm_calls ORDER BY id DESC LIMIT 5;
```

This matters in practice. During development one provider retired a model and
later rate-limited mid-conversation; both times the chain absorbed it with no code
change.

### Asking questions

```bash
curl -H "X-API-Key: change-me" -X POST localhost:8000/agent/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"When should we post and what content works best?","account_id":1}'
```

The agent calls the same analytics functions the API exposes, so it cannot invent
a figure. It is capped at 6 tool calls, its tools are read-only, and the full
trace of what it called and what came back is saved to `agent_runs` and returned
in the response. `GET /agent/runs` lists recent runs.

If the data cannot support an answer it says so. That is the design working, not a
failure.

### Topics and housekeeping

```bash
curl -H "X-API-Key: change-me" -X POST "localhost:8000/topics/run?account_id=1&window=90d"
```

Clusters comments into subjects, each stored with keywords, size and average
sentiment. BERTopic is an optional extra that is not installed in the image (it
requires numba, which caps numpy below the version the KPI engine pins), so this
returns 503 with an install hint unless you install `.[topics]` in an environment
where numpy can be relaxed.

A daily job trims `raw_events` to 30 days and reports what it deleted.

---

## Configuration

Everything is declared in `app/config.py` with a typed default. No module reads
the environment directly. Copy `.env.example` to `.env` and fill in what you need.

| Variable | Purpose |
|---|---|
| `API_KEY` | The `X-API-Key` value clients must send. Default `change-me` |
| `DATABASE_URL`, `REDIS_URL` | Infrastructure, preset for Docker |
| `TZ_DISPLAY` | Bucketing timezone, default `Africa/Tunis` |
| `YOUTUBE_API_KEY`, `YOUTUBE_CHANNEL_IDS` | Live YouTube ingestion |
| `META_PAGE_ACCESS_TOKEN`, `META_PAGE_IDS` | Live Meta ingestion |
| `GROQ_API_KEY`, `GOOGLE_API_KEY`, `OPENROUTER_API_KEY`, `NVIDIA_API_KEY` | LLM providers, any one is enough |
| `LLM_PRIMARY`, `LLM_LONGCTX`, `LLM_FALLBACKS` | The failover chain, in order |
| `ARABIZI_MODEL` | Path or HF id of the fine-tuned model. Empty falls back to the baseline |

`.env` is gitignored. Never commit it.

### Optional extras

Heavy dependencies are split so the image stays buildable and the stack always
boots. Anything behind a missing extra returns 503 with an install hint.

| Extra | Contents | In the image |
|---|---|---|
| `dev` | pytest, ruff, mypy | Yes |
| `nlp` | transformers, CPU torch | Yes |
| `llm` | litellm | Yes |
| `agent` | langgraph | Yes |
| `train` | datasets, accelerate, mlflow | No, runs on Colab or Kaggle |
| `topics` | bertopic, sentence-transformers | No, conflicts with the numpy pin |

---

## Testing

```bash
make test              # everything with coverage, what CI runs
make test-unit         # pure functions only, seconds
make test-integration  # the database-backed tests, on a throwaway db
make lint              # ruff
```

A plain `pytest` reports skips. That is deliberate, not missing coverage: the
database-backed tests drop every table, so they refuse to run unless
`TEST_DATABASE_URL` points at a database whose name contains "test". They never
fall back to the live database, and the check is repeated immediately before every
drop. `make test-integration` creates that throwaway database and runs them, which
is also what CI does.

Without `make` (PowerShell, for example):

```powershell
docker compose exec db psql -U community_management -d community_management -c "CREATE DATABASE community_management_test"
docker compose exec -e TEST_DATABASE_URL=postgresql+psycopg://community_management:community_management@db:5432/community_management_test api pytest -q
```

All 226 tests should pass with nothing skipped.

---

## Layout

```
app/analytics    KPI formulas, aggregation, recommendations
app/nlp          preprocessing, language routing, sentiment, training, topics
app/ingestion    connectors, HTTP client, normalizer, CSV importer, retention
app/llm          provider resolution, failover gateway, generation
app/agent        tool registry, grounding prompt, LangGraph loop
app/api          routers
app/models       SQLAlchemy models
app/workers      Celery app and scheduled jobs
config/          constants and CSV column profiles
alembic/         migrations
tests/           226 tests, mirroring app/
docs/            architecture, data dictionary, algorithms, API reference, report
notebooks/       Kaggle/Colab fine-tuning notebook
```

Each engine is layered the same way: pure functions with no I/O, then pure pandas,
then the single service layer that touches the database, then a thin route. Model
inference sits behind an injectable interface, so the whole pipeline is testable
with a stub and the app boots without the heavy libraries installed.

---

## The rule behind the design

When something cannot be computed honestly, the system says why instead of showing
a number.

A KPI with no denominator returns null and a reason, not zero. A follower count
discloses whether it came from a snapshot or a cached value. Every recommendation
carries the sample size it rests on. Every sentiment label records the model that
produced it. The agent reports unavailable data as unavailable. Topic modeling
refuses to cluster twenty comments into confident themes.

A community manager told "engagement is 0%" when the platform simply does not
publish reach will make a worse decision than one told the number is unavailable,
and why.

---

## Documentation

| Document | Contents |
|---|---|
| `docs/PROJECT_REPORT.md` | Full report: results, decisions, limitations |
| `docs/architecture.md` | Structure, layering, configuration |
| `docs/data_dictionary.md` | Every table and column |
| `docs/models_and_algorithms.md` | Every formula and algorithmic choice |
| `docs/api_reference.md` | Every endpoint with examples |
| `DECISIONS.md` | Each open design choice, with its justification |
