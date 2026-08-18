# Community Management: Intelligence Layer

Final project report. Eight-week internship build of the data and analytics module
for a social media community management application.

Writing convention, kept from the rest of the docs: short sentences, concrete
numbers, no em dashes.

---

## 1. Executive summary

The system ingests a brand's social media posts and comments, computes engagement
KPIs, scores comment sentiment across French, English, Arabic and Tunisian
Arabizi, turns that history into posting recommendations, and answers plain
language questions about it all with an agent that can only cite real numbers.

It runs end to end on `docker compose up`. It is built on live public data, not
mock data: 221 posts and 1,849 comments ingested from two real YouTube channels
plus three synthetic demo accounts.

Delivered:

| Metric | Value |
|---|---|
| Roadmap weeks completed | 8 of 8 |
| Automated tests | 226 passing, 0 failing |
| Coverage | 97% on `app/analytics`, 86% on `app/nlp` |
| Lint | ruff clean across `app/` and `tests/` |
| CI | GitHub Actions, tests and lint as hard gates |
| API endpoints | 24 across 8 routers |
| Database tables | 14 |
| Live data ingested | 221 posts, 442 metric snapshots, 1,849 comments |
| Comments sentiment-scored | 1,849 across 5 language buckets |
| Custom model trained | Tunisian Arabizi classifier, 72.2% held-out accuracy |

The differentiator is the Tunisian Arabizi handling. Generic sentiment models and
language detectors fail on dialect written in Latin letters and digits
("3ajbetni barcha", "ya3tik sa7a"). This system routes that register with a
deterministic rule layer and classifies it with a model fine-tuned for it.

---

## 2. The problem

A community manager for a Tunisian brand faces three practical difficulties.

**Their audience writes in a register the tools do not understand.** Comments
arrive in French, English, Modern Standard Arabic, and Tunisian Arabizi, often
mixed in one thread. Off-the-shelf sentiment tools treat Arabizi as noise or
misclassify it as an unrelated Latin-script language.

**The numbers platforms expose are inconsistent.** Instagram and Facebook report
reach; public YouTube does not. A dashboard that silently prints 0 for a missing
reach figure produces engagement rates that are quietly wrong.

**Advice without evidence is unusable.** "Post on Thursday at 8pm" means nothing
without knowing whether it rests on 2 posts or 40, and how much better than
average it actually is.

The system answers all three deliberately, and those answers shape its design.

---

## 3. Architecture

### 3.1 Stack

| Layer | Choice | Reason |
|---|---|---|
| API | FastAPI + Pydantic v2 | Typed request/response contracts, OpenAPI for free |
| ORM | SQLAlchemy 2.0 | Explicit `select()` style, real upsert support |
| Database | PostgreSQL 16 + pgvector | JSONB, arrays, `ON CONFLICT`, embeddings in one store |
| Cache/broker | Redis 7 | KPI and LLM response cache, Celery transport |
| Scheduler | Celery + beat | Ingestion, sentiment, retention jobs |
| NLP | transformers, CPU torch | Multilingual sentiment, Arabizi fine-tune |
| LLM | litellm | One interface across five free providers |
| Agent | LangGraph | Explicit think/act state machine |
| Runtime | Docker Compose | Five services, one command |

### 3.2 Layering rule

Every engine follows the same three-layer split, and the rule is enforced by the
tests rather than by convention alone:

```
pure functions   no I/O, no clock, no DB. Unit-tested against hand-computed values.
       |
pure pandas      DataFrame in, chart-ready structure out. Still no DB.
       |
service layer    the only code that touches the database. Assembles API responses.
       |
route            thin. Validates, calls one service function, owns the commit.
```

The payoff is concrete. `app/analytics/kpi.py` and `app/analytics/recommend.py`
contain every formula the product depends on, and they are tested with no
database, no network and no fixtures. When a KPI is wrong, there is exactly one
place to look.

### 3.3 Injectable model backends

Sentiment, topics and the LLM gateway all sit behind a `Protocol` with the real
implementation lazy-loaded on first use. Consequences:

- The full pipeline is unit-tested with a stub, without downloading a 1 GB model.
- The application boots even when a heavy extra is not installed.
- Swapping the Arabizi baseline for the fine-tuned model is one environment
  variable, with no code change and no interface change.
- Anything requiring a missing extra returns HTTP 503 with an install hint, never
  an obscure crash.

### 3.4 Data flow

```
YouTube API ─┐
Meta Graph  ─┼─> connector ─> normalizer ─> Postgres ─> KPI engine ──────┐
CSV export  ─┘   (retry,       (idempotent   (snapshots,   sentiment ────┼─> API
                  cursors)      upserts)      raw_events)   recommender ─┤
                                                            topics ──────┘
                                                                │
                                                     agent (read-only tools)
                                                                │
                                                          LLM gateway
                                                        (failover chain)
```

---

## 4. Data foundation

### 4.1 Schema principles

14 tables. Four decisions matter more than the rest.

**Snapshots, not counters.** `post_metric_snapshots` is append-only. A post's
"current" likes are its most recent snapshot, selected with a per-post
`MAX(captured_at)` join. Overwriting a counter destroys the growth curve, which is
what engagement velocity needs.

**One honest source for followers.** `follower_snapshots` is truth;
`accounts.followers_count` is a denormalized cache. KPI code reads snapshots and
falls back to the cache only with the basis disclosed in the response.

**Idempotency by construction.** Every ingestion path uses
`insert().on_conflict_do_update` on natural keys. Re-running any job inserts zero
duplicates. Metric snapshots use `on_conflict_do_nothing`, because a snapshot at a
given instant is immutable.

**Raw payload archive.** Every API response is stored in `raw_events` for
debugging and reprocessing, capped at 30 days by a daily purge job.

### 4.2 Sources

| Source | Status | Volume | Note |
|---|---|---|---|
| YouTube Data API v3 | Live | 2 channels, 101 posts, 1,387 comments | Public channels, API key only, no OAuth |
| Meta Graph API | Implemented, offline-tested | Canned payloads | Needs a page token to run live |
| CSV import | Live | Business Suite + Kaggle profiles | Column mapping is config, not code |
| Synthetic fixtures | Live | 3 accounts, 120 posts | Flagged `is_synthetic`, never shown as real |

Reach and impressions are owner-private on public YouTube. Rather than
substituting zero, reach-based KPIs return null with the reason
`reach_unavailable`, and the engine falls back to a follower-based rate with the
basis stated in the response.

---

## 5. Delivery by week

| Week | Delivered | Evidence |
|---|---|---|
| 1 | Schema, migrations, Docker Compose, CSV importer, fixtures, health | Stack boots with no API key |
| 2 | KPI engine, temporal aggregation, z-scores, 4 endpoints, Redis cache | Hand-computed unit tests |
| 3a | Preprocessing, language routing, multilingual sentiment, batch job | 9/9 routing on seeded registers |
| 3b | YouTube + Meta connectors, resilient HTTP, cursor sync | 1,387 real comments ingested |
| 4 | Arabizi fine-tune (Model B), training + evaluation modules | 72.2% held-out accuracy |
| 5 | Recommendation engine with evidence and shrinkage | 4 endpoints, live output verified |
| 6 | Multi-provider LLM gateway, caption generation | Survived 2 real provider failures |
| 7 | LangGraph analyst agent, 10 read-only tools, traces | Grounded answers, 6-call budget |
| 8 | Topic modeling, 30-day retention purge, documentation | 226 tests green |

---

## 6. The engines

### 6.1 KPI engine

Eleven post-level KPIs and six account-level ones, each a pure function tested
against a hand-computed fixture.

The rule that shapes it: **a rate whose denominator is missing or non-positive
returns null with a stable reason code, never 0.** A zero claims "this happened
and scored nothing". A null says "this cannot be computed, and here is why".
Reason codes are a fixed vocabulary (`reach_unavailable`,
`non_positive_denominator`, `insufficient_snapshots`, ...) that the dashboard can
branch on. A zero numerator over a positive denominator is a truthful `0.0`.

Two subtleties worth recording:

**Primary rate with a disclosed basis.** Engagement rate is by reach when reach
exists, else by followers, and the basis travels with every response. This keeps a
mixed Instagram/Facebook/YouTube feed comparable instead of half null.

**Bucketing in pandas Period space throughout.** Mixing `to_period` with
`date_range` misaligns weekly and monthly anchors and silently zeroes real
buckets. This bug appeared during Week 2, was fixed, and now has a regression test
covering weekly and monthly gap-fill.

Cross-platform comparison reports each platform's z-score against its own trailing
90-day baseline, because raw engagement rates are not comparable across platforms.

### 6.2 Multilingual sentiment

Pipeline: `comment -> preprocess -> detect language -> classify -> store label`.

**Preprocessing** is deterministic and pure. Mentions become `@user` and URLs
become `http` (the convention the model was trained on), character floods collapse
keeping one repeat as an intensity signal, Arabic letters are normalized, and
emojis are preserved and separately scored.

**Language routing** is the custom part. Generic detectors mislabel Tunisian
Arabizi, so a deterministic rule layer runs before the base detector:

1. Mostly Arabic script goes to `ar`.
2. Latin script plus an Arabizi signal goes to `aeb-latn`. The signal is a digit
   used as a letter inside a word (a Latin letter adjacent to 2/3/5/6/7/8/9) or a
   hit in a curated Tunisian lexicon (barcha, behi, yesser, sa7a, 3aslema). A pure
   number like "300" does not trigger it.
3. Otherwise the base detector returns fr or en, else `other`.

Every result carries a confidence and the method used, so a label is auditable.

**Classification** uses `cardiffnlp/twitter-xlm-roberta-base-sentiment` behind the
injectable backend. Every stored label records `model_name` and `model_version`,
so a model upgrade is traceable and re-labelling is clean.

Live distribution over 1,849 real comments:

| Language | Comments |
|---|---|
| ar | 1,180 |
| other | 224 |
| en | 205 |
| aeb-latn | 144 |
| fr | 96 |

### 6.3 The Arabizi specialist (Model B)

Fine-tuned `cardiffnlp/twitter-xlm-roberta-base` on the TUNIZI corpus: 3,000
Tunisian Arabizi sentences, balanced 1,500 positive and 1,500 negative, annotated
by native speakers.

Protocol: seeded stratified 70/10/20 split, max length 128, lr 2e-5, AdamW, 4
epochs with early stopping on validation macro-F1, inverse-frequency class
weights, MLflow logging, model card written next to the weights. Training input is
cleaned with the exact `preprocess` used at inference, which removes train/serve
skew. Label id order matches the base model, so the app loads the fine-tuned
weights with no change to the inference layer. Trained on a free Kaggle T4 in
about 2.5 minutes.

Held-out test set results (600 rows):

| Metric | Value |
|---|---|
| Accuracy | 0.7217 |
| Macro-F1 (3-class) | 0.4811 |
| F1 positive | 0.7184 (n=300) |
| F1 negative | 0.7249 (n=300) |
| F1 neutral | 0.0 (n=0, class absent from TUNIZI) |

Per-language on the same set:

| Language | Accuracy | n |
|---|---|---|
| fr | 0.8462 | 13 |
| aeb-latn | 0.7241 | 395 |
| other | 0.7135 | 171 |
| en | 0.6667 | 21 |

The macro-F1 of 0.48 is deflated by construction, not by weakness: TUNIZI is a
binary corpus, so the absent neutral class contributes a mandatory 0.0 to a
three-class average. The honest headline is 72% accuracy with balanced performance
across both present classes (0.718 and 0.725), on a dialect with no standard
orthography.

**Deployment.** Setting `ARABIZI_MODEL` routes `aeb-latn` text to the specialist
and everything else to the multilingual baseline. All 144 live Arabizi comments
were re-labelled and now carry `model_version = tunizi-arabizi-1.0`. When the
variable is empty the system falls back to the baseline and flags each label
`needs_arabizi_specialist`, so a provisional label is never presented as final.

### 6.4 Recommendation engine

Three recommendations: best time to post (day and hour in Africa/Tunis, plus day
and hour marginals), best content type, and best hashtags.

**Every item carries its evidence**: `n` (sample size), `lift` (versus the
account's own baseline engagement rate), and a `confidence` tier derived from the
sample size (n>=8 high, n>=4 medium, n>=2 low, below that not surfaced at all).

**Ranking uses shrinkage, not the raw mean.** A single lucky post at 3am must not
beat a well-sampled slot, so each group's score is

```
shrunk_score = (sum(engagement_rate) + K * baseline) / (n + K),  K = 5
```

A group with n far below K sits near the baseline and cannot top the list on
noise. This is visible in live output: for one account the highest raw mean (6.6%)
belonged to an hour with n=1, and it correctly ranked below an hour with n=5 and a
lower raw mean. The raw mean is still reported, so nothing is hidden.

Times are bucketed in Africa/Tunis, not UTC, because "Thursday 8pm" is only
meaningful in the client's local time. Hashtag extraction is Unicode-aware, so
Arabic tags such as `#نجاح` are ranked alongside `#promo`.

Insufficient data returns a reason, never a fabricated pick. Every generated
recommendation is written to the `recommendations` table with its evidence, giving
an auditable history of what was advised and on what basis.

### 6.5 LLM gateway

A gateway over five free-tier providers (Groq, Gemini, OpenRouter, NVIDIA NIM,
local Ollama), built around failover because no free tier is dependable alone.

A request walks a chain assembled from `LLM_PRIMARY`, `LLM_LONGCTX` and
`LLM_FALLBACKS`, with any model whose provider key is unset dropped before it is
tried. The first success wins. Every attempt writes an `llm_calls` row with
provider, model, tokens, latency, status, fallback depth and, when it failed, the
provider's own error message.

**This design was validated by two unplanned real failures during development:**

1. Groq retired `llama-3.3-70b-versatile` mid-project. The gateway fell through to
   Gemini and kept answering. Fixing it was one line in `.env`.
2. The replacement model hit a free-tier rate limit partway through a multi-step
   agent conversation. Groq answered two turns, hit its quota on the third, and
   Gemini completed the reasoning loop. The user saw no failure.

Neither required a code change. The second case also drove a small improvement:
the provider's error message is now persisted to `llm_calls.error`, so a failover
is diagnosable with a SQL query rather than by grepping container logs.

Caption generation sits on top. It asks for a JSON array and parses defensively
across four reply shapes (raw array, fenced block, wrapper object, numbered list),
because models are inconsistent and a malformed reply should degrade the result,
never return a 500. Passing an `account_id` feeds the account's recent posts to
the model as a brand-voice reference; live output picked up the account's own
hashtags unprompted.

### 6.6 Analyst agent

A LangGraph think/act loop that answers questions like "when should we post and
what content works best?".

**Its ten tools are the project's own tested functions**: KPI overview,
timeseries, top posts, platform comparison, sentiment summary, negative alerts,
the three recommendation kinds, and an account list. This is what makes grounding
a property of the system rather than a promise in a prompt. The agent cannot
compute a number a different way than the dashboard does.

Three safety properties are enforced in the tool registry, not the prompt, because
a prompt can be argued out of a rule and code cannot:

- **Read-only.** No tool writes. Recommendation tools run with `persist=False`, so
  asking a question leaves no rows behind.
- **Bounded.** Arguments are coerced and clamped. List limits cap at 20, window
  strings are validated by the KPI parser and fall back to a default rather than
  raising. A malformed model argument cannot become an unbounded query.
- **Non-fatal.** A tool failure returns `{"error": ...}` for the model to read and
  report. A bad tool call degrades the answer, it never becomes a 500.

The loop is capped at 6 tool calls, matching the data dictionary. When the budget
is spent, a `finalize` node forces a written answer from what was gathered, so a
runaway model still returns something useful. This was verified: a deliberately
greedy stub that always requests another tool stopped at exactly 6 and answered.

Every run persists to `agent_runs` with the question, answer, tool call count and
the full trace of each call, its arguments, its outcome and its result.

A verified live answer, checked figure by figure against its own trace:

> Over the last 120 days (n=37 posts), the best time to post is Sunday at 9 PM
> (n=2 posts, 1.2x lift, low confidence) or Friday at 4 PM. By day, Friday
> performs best (n=7, 1.12x lift, medium confidence). By hour, 4 PM performs best
> (n=4, 1.22x lift, medium confidence). Video content performs best (n=9, 1.09x
> lift, high confidence).

Every number matched a tool result. The agent also made the right editorial
judgment: it led with the day and hour marginals, which have more data, and
labelled the sparse two-post cell as low confidence.

Earlier, asked a question whose window contained no posts, it reported that the
data was insufficient rather than inventing a plausible answer. That refusal is
the behaviour the whole design exists to produce.

### 6.7 Topics and retention

Topic clustering answers what people are discussing, complementing sentiment's how
they feel. Each cluster is stored with its keywords, size and average sentiment,
and clustered comments are linked by `comment_analyses.topic_id`, so
sentiment-by-subject is a join rather than a second model run.

Labels are deterministic keyword joins, not LLM-generated, because a topic whose
name changes between runs makes trends impossible to follow. Below 20 comments the
service returns `insufficient_data` instead of clustering noise into confident
looking themes. Outliers and clusters below the minimum size are never presented
as topics. Re-running replaces a window's rows, so the job is idempotent.

BERTopic is an optional extra and is deliberately not in the application image.
It requires numba, which caps numpy below 2.1, while the analytics layer pins
numpy 2.2.1. Downgrading a pin the KPI engine depends on, for a secondary feature,
was the wrong trade. The endpoints ship and are fully tested behind a stub
backend, and answer 503 with an install hint when the extra is absent.

Retention: `raw_events` is capped at 30 days by a daily Celery job that reports
what it deleted, what remains and the oldest surviving row, so a scheduled job
leaves evidence that it ran.

---

## 7. Engineering practices

### 7.1 Testing

226 tests, structured to mirror the layering.

| Kind | Count | Needs |
|---|---|---|
| Pure unit | 163 | Nothing. Run anywhere, in seconds |
| Integration | 63 | A PostgreSQL database named like a test database |

Pure tests are checked against values computed by hand in the test comments, so
production math is pinned to an independent calculation rather than to itself.

Coverage on the two areas the brief targets, measured in CI:

| Package | Coverage | Note |
|---|---|---|
| `app/analytics` | 97% | 527 statements, 15 uncovered |
| `app/nlp` | 86% | Excluding the two offline training CLIs |

What remains uncovered is almost entirely the real model backends
(`TransformersBackend`, `BERTopicBackend`), which cannot execute in CI because the
`nlp` and `topics` extras are deliberately not installed there. That is the cost of
the injectable-backend design, and it is the right trade: the routing, assembly,
persistence and error handling around those backends are fully covered, while
downloading a gigabyte of weights per CI run would buy almost nothing.

The two fine-tuning CLI scripts are excluded from the measurement in
`pyproject.toml`. They run on a Colab or Kaggle GPU with a dataset, nothing in the
served application imports them, and counting them would understate coverage of
the code that actually runs. The pure logic they rely on (`training/data.py` and
`training/metrics.py`) is at 100% and stays measured.

**Destructive fixtures cannot touch live data.** Integration fixtures drop every
table, so three independent guards must agree before anything runs: the suite uses
`TEST_DATABASE_URL` and never falls back to `DATABASE_URL`; the target must differ
from the live URL and its name must contain "test"; and the check is repeated
immediately before every `drop_all`. A misconfiguration fails loudly instead of
wiping data. `make test-integration` creates the throwaway database and runs them.

**A real bug this caught.** Week 3 API tests shared one session, which hid a
service that never committed: `/sentiment/run` reported 457 comments analyzed
while the database held none. The fixture was rewritten to give each request its
own session, exactly like production, so cross-request visibility now requires a
real commit. The fixture was then verified by removing the commit and confirming
the test fails.

### 7.2 CI and quality gates

GitHub Actions runs the suite against PostgreSQL with pgvector plus Redis, then
ruff, both as hard gates. Ruff enforces pycodestyle, pyflakes, isort, bugbear,
pyupgrade and naming rules. Notebooks are excluded, since interleaving imports
with code is normal there and is not application code.

### 7.3 Configuration and secrets

No module reads the environment directly. `app/config.py` declares every variable
with a typed default, and the singleton is imported. Model names, provider order,
content-type maps and CSV column profiles live in `config/`, never inline, because
platform field names and free-tier catalogs change often.

`.env` is gitignored and `.env.example` is committed. Model weights live in a
gitignored `models/` directory and are mounted into the container, never committed.

---

## 8. The principle running through it

One idea connects every module: **when something cannot be computed honestly, say
why instead of showing a number.**

| Where | How it appears |
|---|---|
| KPIs | Null with a stable reason code, never a lying zero |
| Follower counts | The basis (`snapshot` or `account_latest`) is always disclosed |
| Engagement rate | The basis (reach or followers) travels with every response |
| Recommendations | n, lift and confidence on every item; thin data returns a reason |
| Sentiment | Model name and version on every label; provisional labels flagged |
| Cross-platform | z-score against each platform's own baseline, not a raw comparison |
| Topics | Below 20 comments, refuse rather than cluster noise |
| Agent | Only tool-derived numbers; unavailable data reported as unavailable |
| LLM | Every attempt logged, including failures and their provider message |
| Missing extras | 503 with an install hint, never an obscure crash |

This is not decoration. A community manager who is told "engagement is 0%" when
the platform simply does not expose reach will make a worse decision than one who
is told the figure is unavailable and why.

---

## 9. Limitations

Stated plainly, because a report that claims no weaknesses is not credible.

**The Arabizi model has not been compared against the baseline.** The fine-tuned
model reports 72.2% held-out accuracy, but the before/after table against the
multilingual baseline was not produced. The evaluation script exists and takes one
command; the number is simply not yet measured. No lift claim is made without it.

**TUNIZI is small and binary.** 3,000 sentences, positive and negative only. The
model will not predict neutral for Arabizi, which is a real limitation for
comments that are genuinely neutral. A larger corpus with a neutral class, or a
gold set annotated from the client's own comments with inter-annotator agreement
reported, would be the next step.

**Errors on hard cases are real.** A live test on "khayeb barcha ma3jbetnich el
produit" (clearly negative, using the Tunisian negation ma...ch) returned
positive. Short negated phrases remain difficult with 3,000 training examples.

**Reach-based KPIs are null on public sources.** This is correct behaviour, not a
defect, but it means several KPIs are unavailable for YouTube accounts. A brand
connecting its own accounts with owner permissions would populate them.

**Meta connector is not live-verified.** It is implemented and tested against
canned payloads, but it has not run against a real page token.

**Free-tier LLMs rate limit constantly.** The gateway handles this by design, but
agent latency varies from under a second to several seconds depending on how far
down the chain a request falls.

**Topic modeling is not installed in the image.** The numpy conflict is documented
and the code is tested behind a stub, but BERTopic has not been run on this
project's real comments.

**Synthetic fixtures are included by default in KPI queries.** They are flagged
`is_synthetic` and can be excluded per request, but the default is to include
them, which is convenient for demos and would be wrong in production.

---

## 10. What would come next

In priority order:

1. Run the Model A versus Model B comparison and publish the per-language table.
2. Build a gold set of about 200 comments from real client data, annotated by two
   people with Cohen's kappa reported, and evaluate against it.
3. Take the Meta connector live with a self-owned test page.
4. Add the embedding layer that the pgvector column already anticipates, for
   comment similarity and brand-voice retrieval.
5. Run BERTopic in a dedicated worker image where numpy can be relaxed.
6. Add forecasting (SARIMAX is already the documented default choice) and anomaly
   detection on the KPI timeseries.

---

## Appendix A: endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health/live` | Liveness, no auth |
| GET | `/health` | Readiness with dependency status |
| GET | `/meta/models` | Loaded models and versions |
| POST | `/ingestion/csv` | Import an official export |
| GET | `/ingestion/status` | Row counts and sync cursors |
| POST | `/ingestion/run` | Incremental live sync |
| GET | `/kpi/overview` | Headline KPIs plus deltas |
| GET | `/kpi/timeseries` | Any metric over time, gap-filled |
| GET | `/kpi/by-platform` | Cross-platform with z-scores |
| GET | `/kpi/top-posts` | Ranked posts with KPI breakdown |
| POST | `/sentiment/analyze` | Ad hoc text classification |
| POST | `/sentiment/run` | Batch analyze stored comments |
| GET | `/sentiment/summary` | Distribution, languages, trend |
| GET | `/sentiment/negative-alerts` | Negative spikes and comments |
| POST | `/recommendations/best-time` | Day and hour slots with evidence |
| POST | `/recommendations/content-types` | Content type ranking |
| POST | `/recommendations/hashtags` | Hashtag ranking |
| POST | `/recommendations/all` | All three at once |
| GET | `/llm/providers` | Configured providers and chain |
| POST | `/llm/generate` | Caption options for a brief |
| POST | `/agent/ask` | Grounded question answering |
| GET | `/agent/runs` | Recent runs with tool traces |
| POST | `/topics/run` | Cluster comments into topics |
| GET | `/topics` | Stored topics for an account |

## Appendix B: repository layout

```
app/analytics    KPI formulas, aggregation, recommendations
app/nlp          preprocessing, language routing, sentiment, training, topics
app/ingestion    connectors, HTTP client, normalizer, CSV importer, retention
app/llm          provider resolution, failover gateway, generation
app/agent        tool registry, grounding prompt, LangGraph loop
app/api          routers
app/models       SQLAlchemy models
app/workers      Celery app and scheduled tasks
config/          constants and CSV column profiles
alembic/         migrations
tests/           226 tests, mirroring app/
docs/            architecture, data dictionary, models and algorithms, API, this report
notebooks/       Kaggle/Colab fine-tuning notebook
```

## Appendix C: documentation map

| Document | Contents |
|---|---|
| `README.md` | What it is, how to run it, how each part works |
| `docs/architecture.md` | Structure, layering, configuration |
| `docs/data_dictionary.md` | Every table and column |
| `docs/models_and_algorithms.md` | Every formula and algorithmic choice |
| `docs/api_reference.md` | Every endpoint with examples |
| `DECISIONS.md` | Each open design choice, with its justification |
| `docs/PROJECT_REPORT.md` | This report |
