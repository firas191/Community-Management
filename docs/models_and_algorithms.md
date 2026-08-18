# Models and Algorithms

This is the livrable "documentation des modeles et algorithmes". It records every
formula and every algorithmic choice, in the order the roadmap builds them. Each
KPI is a pure function unit-tested against a hand-computed fixture, so the numbers
in production match the numbers in the tests.

Writing convention: short sentences, concrete numbers, no em dashes.

## 1. KPI Engine (Week 2)

### 1.1 The honesty rule

A rate whose denominator is missing or non-positive returns null with a stable
reason code, never 0. A zero would claim "this happened and scored nothing". A
null says "this cannot be computed, and here is why". Reason codes are a fixed
vocabulary the dashboard can branch on:

- `reach_unavailable`, `followers_unavailable`, `impressions_unavailable`,
  `clicks_unavailable`, `video_views_unavailable`: the platform does not expose
  that field for this row.
- `non_positive_denominator`: the field is present but zero or negative, so a
  rate is undefined.
- `insufficient_snapshots`: needs at least two metric snapshots (velocity).
- `insufficient_data`: not enough posts or history for the statistic.

A zero numerator over a positive denominator is a truthful `0.0`, not a null.

### 1.2 Post-level KPIs

Let L = likes, C = comments, S = shares, Sv = saves, R = reach, I = impressions,
F = followers at publish time. Engagement E = L + C + S + Sv. All rates are
percentages rounded to 2 decimals.

| KPI | Formula | Null reason when undefined |
|---|---|---|
| Engagement rate by reach (ERR) | E / R * 100 | reach_unavailable |
| Engagement rate by followers (ERF) | E / F * 100 | followers_unavailable |
| Engagement rate by impressions | E / I * 100 | impressions_unavailable |
| Amplification rate | S / F * 100 | followers_unavailable |
| Applause rate | L / F * 100 | followers_unavailable |
| Conversation rate | C / F * 100 | followers_unavailable |
| Save rate | Sv / R * 100 | reach_unavailable |
| Virality rate | S / R * 100 | reach_unavailable |
| Click-through rate | clicks / I * 100 | clicks_unavailable |
| Video view rate | video_views / R * 100 | video_views_unavailable |
| Engagement velocity | E(first 24h) / E(total) | insufficient_snapshots |

Engagement velocity is a ratio in 0..1, not a percentage. It needs the first-24h
snapshot, so with a single snapshot (a CSV import or one live fetch) it returns
`insufficient_snapshots` rather than a fabricated number.

### 1.3 Primary engagement rate and basis

Public sources differ: Instagram and Facebook expose reach, public YouTube does
not. The primary per-post engagement rate is ERR when reach exists, else ERF. The
chosen basis (`err`, `erf`, or `none`) is returned with every aggregate so a
mixed feed stays honest and comparable. This is why the YouTube overview reports
`engagement_rate_basis: erf` instead of a column of nulls.

### 1.4 Account-level KPIs

- Average engagement rate: mean and median are both reported. The ER
  distribution is right-skewed, so the median is the more robust headline.
- Posting frequency: posts / (window_days / 7), in posts per week.
- Posting consistency: standard deviation, in hours, of the gaps between
  consecutive posts. Lower is steadier. Needs at least 3 posts.
- Follower growth rate: (F_end - F_start) / F_start * 100.
- Net follower change: F_end - F_start.
- Period-over-period delta: (current - previous) / abs(previous) * 100, computed
  against the immediately preceding window of equal length.

### 1.5 Follower resolution

Truth for follower counts is the `follower_snapshots` time series (brief 6.2).
For a given moment the engine takes the nearest snapshot within 7 days. When no
snapshot exists (back-imported posts that predate snapshotting, or fixtures with
no snapshot job yet), it falls back to the account's denormalized latest
`followers_count` and labels the basis `account_latest`. It returns null only
when neither source exists. The basis is always disclosed, so the source of a
follower number is never hidden. This refines the stricter Week 1 note in
DECISIONS.md, which is recorded there.

### 1.6 Temporal aggregation

- Granularity: hour, day, week (ISO, Monday-anchored), month.
- Timezone: timestamps are stored in UTC and bucketed in Africa/Tunis, so a
  "Thursday evening" bucket matches the Tunisian market.
- Bucketing runs entirely in pandas Period space. Gap-fill reindexes onto a
  `period_range` of the same frequency. Mixing `to_period` with `date_range`
  misaligns weekly and monthly anchors and silently zeroes real buckets, so the
  code never does that. A regression test covers weekly and monthly gap-fill.
- Missing buckets are filled with explicit zeros so a chart never shows a false
  break in the line.
- A bucket-level engagement rate pools the numerator and denominator across the
  bucket (sum of engagement over sum of reach). It is never a mean of per-post
  ratios, which would over-weight small posts.
- Rolling means (any window) are offered as an extra series for smoothing weekday
  seasonality. The first (window - 1) points are null, not back-filled.

### 1.7 Cross-platform comparison

Raw engagement rates are not comparable across platforms, because Instagram runs
structurally higher than Facebook. Two views are provided. The raw table shows
the same KPIs side by side with a comparability caveat. The normalized view
reports a z-score of each platform's current window against its own trailing
90-day daily baseline: (current - mean) / stdev, sample standard deviation. It
needs at least two baseline points and non-zero variance, else it returns null
with a reason. "Instagram is +1.3 sigma versus its own baseline" is the correct
answer to "which platform is doing better".

### 1.8 Caching

KPI responses are cached in Redis for 15 minutes, keyed by endpoint and a hash of
the query parameters. The cache is a pure optimization. If Redis is unreachable
the endpoint logs a warning, computes the answer, and serves it. No number ever
depends on the cache being up.

## 2. Sentiment pipeline (Week 3)

The pipeline turns a raw comment into a traceable sentiment label across four
registers: French, English, Modern Standard Arabic, and Tunisian Arabizi.

```
comment -> preprocess -> detect language -> classify (Model A) -> store label
```

### 2.1 Preprocessing

Deterministic and pure (`nlp/preprocessing.py`). @mentions become `@user` and
URLs become `http` (the cardiffnlp training convention, which improves accuracy).
Character floods are collapsed keeping one repeat as an intensity signal
(`barchaaaa -> barchaa`). Arabic letters are normalized (alef/hamza variants
unified, diacritics and tatweel dropped, `ة -> ه`, `ى -> ي`). Emojis are
preserved for the model and also scored on a curated polarity lexicon for the
emoji-analytics feature. An Arabizi digit-to-Arabic map (`3 -> ع`, `7 -> ح`,
`9 -> ق`, `5 -> خ`) is documented and exported for the Week 4 fine-tuned model.

### 2.2 Language routing (the differentiator)

The valuable, hard case is Tunisian Arabizi: dialect in Latin letters and digits
("3ajbetni barcha", "ya3tik sa7a"). Generic detectors mislabel it. The router
(`nlp/language.py`) is deterministic on top of a pluggable base detector:

1. Mostly Arabic script -> `ar`.
2. Latin script AND an Arabizi signal -> `aeb-latn`. The signal is (a) digits
   used as letters intra-word (a Latin letter adjacent to 2/3/5/6/7/8/9) or
   (b) a curated Tunisian lexicon hit ("barcha", "behi", "yesser", "sa7a",
   "3aslema", ...). A pure number like "300" does not trigger it.
3. Otherwise the base detector (langdetect, or a heuristic offline) returns
   `fr` / `en`, else `other`.

Each result carries a confidence and the method used (`script`, `arabizi_rule`,
`base_detector`, `heuristic`). fastText lid.176 can replace the base detector
behind one function without touching the rule layer. On the seeded multilingual
set the router labels all four registers correctly (9/9).

### 2.3 Sentiment model (Model A)

`cardiffnlp/twitter-xlm-roberta-base-sentiment`: XLM-RoBERTa fine-tuned for
three-class sentiment (positive / neutral / negative) across the project's
languages. The model sits behind a `SentimentBackend` Protocol and is
lazy-loaded on first use, so the app boots and the whole pipeline is unit-tested
without downloading weights (a stub backend is injected in tests). fr / en / ar
and unknown route to Model A. Arabizi also uses Model A for now, flagged
`needs_arabizi_specialist`; the fine-tuned Arabizi model (Model B) replaces that
path in Week 4 without changing the interface. Every stored label records
`model_name` and `model_version` for reproducibility.

### 2.4 Aggregation

Sentiment maps to a net score for rollups: positive = +1, neutral = 0,
negative = -1; the window mean lands in [-1, 1]. The summary reports the
distribution, a per-language breakdown, a daily net-sentiment trend, and deltas
versus the previous window. Negative alerting flags a day whose negative share
exceeds mean + 2 sigma with at least 10 comments (brief Section 11.5).

## 3. Fine-tuned Arabizi model, Model B (Week 4)

Model A is multilingual but only incidentally good at Tunisian Arabizi. Model B is
a specialist fine-tuned on the TUNIZI corpus (Tunisian Arabizi sentiment, labelled
by native speakers) and routed to only for `aeb-latn` text.

### 3.1 Training protocol

`app/nlp/training/finetune_tunizi.py` (runs on a free Colab/Kaggle GPU; see
`notebooks/finetune_tunizi.ipynb`):

- Base model: `cardiffnlp/twitter-xlm-roberta-base` (same family as Model A).
- Input is cleaned by the exact `preprocess` used at inference, so train and serve
  match. Labels are normalized to positive/neutral/negative.
- Seeded stratified 70/10/20 split, so the reported numbers are reproducible.
- Max length 128, lr 2e-5, AdamW, up to 4 epochs, early stopping on validation
  macro-F1. Class weights (inverse frequency) counter the class imbalance.
- Label id order matches Model A (0=negative, 1=neutral, 2=positive), so the app
  loads Model B with no change to the inference layer.
- Everything is logged to MLflow; a model card and `metrics.json` are saved next to
  the weights.

### 3.2 Evaluation protocol

Accuracy is the honest primary metric here, plus per-class precision/recall
(`app/nlp/training/metrics.py`, pure and unit-tested). `app/nlp/training/evaluate.py`
runs the same held-out set through Model A and Model B and prints the per-language
table; the delta on `aeb-latn` is the headline.

Result on the held-out TUNIZI test set (600 rows, seed 42, 4 epochs on a T4):
accuracy 0.722, with balanced per-class F1 (positive 0.718, negative 0.725).

| Language | Model B accuracy | Model B macro-F1 | n |
|---|---|---|---|
| aeb-latn | 0.724 | 0.480 | 395 |
| other    | 0.714 | 0.470 | 171 |
| fr       | 0.846 | 0.564 | 13  |
| en       | 0.667 | 0.407 | 21  |

Note on the macro-F1 numbers: TUNIZI is a binary corpus (positive/negative, no
neutral), so the three-class macro-F1 averages in an unavoidable 0.0 for the absent
neutral class and lands near 0.48. The real signal is the ~0.72 accuracy and the
~0.72 F1 on each of the two present classes. The `evaluate.py` before/after run
produces the Model A baseline column and the `aeb-latn` delta for the report.

A ~200-comment gold set from real client comments, annotated by two people with
Cohen's kappa reported, would make the evaluation even more credible (brief
Section 9.2).

### 3.3 Serving Model B

The routing layer never changes. Set `ARABIZI_MODEL` to the fine-tuned model (a
local path mounted into the container, or a HuggingFace id) and the analyzer sends
`aeb-latn` text to Model B and everything else to Model A. When `ARABIZI_MODEL` is
empty, Arabizi falls back to Model A and is flagged `needs_arabizi_specialist`.
Each stored label records which model produced it (`model_name`, `model_version`),
so a model swap is fully traceable.

## 4. Recommendation engine (Week 5)

Turns an account's posts into explainable recommendations: best time to post,
best content type, and best hashtags. Every recommendation carries its evidence,
so the dashboard can justify each pick rather than assert it (brief Section 8.5).
Same strict layering as the KPI engine: `analytics/recommend.py` is pure math,
`analytics/recommend_service.py` is the only DB-facing layer.

### 4.1 Evidence on every recommendation

Each ranked item reports three things:

- `n`: the sample size the pick rests on.
- `lift`: the group's mean engagement rate divided by the account's own baseline
  (the mean ER across all its posts in the window). `lift > 1` means above average.
- `confidence`: a tier from the sample size. `n >= 8` is `high`, `n >= 4` is
  `medium`, `n >= 2` is `low`, and below 2 the group is too thin to surface at all
  (`confidence: null`). Thresholds live in one place and are easy to tune.

### 4.2 Shrinkage so small samples do not win on luck

Ranking by raw mean lets a single lucky post at 3am beat a well-sampled slot. To
prevent that, each group is ranked by a shrinkage estimate that pulls thin groups
toward the baseline:

```
shrunk_score = (sum(engagement_rate) + K * baseline) / (n + K),  K = 5
```

A group with `n` far below `K` sits near the baseline and cannot top the list on
noise; a well-sampled group is dominated by its own mean. `K = 5` means a slot
needs on the order of five posts before its own average carries the ranking. The
raw mean is still reported next to the shrunk score, so nothing is hidden. This is
a standard empirical-Bayes shrinkage, chosen because it needs no per-account tuning.

### 4.3 Best time to post

Publish times are converted from UTC to the display timezone (Africa/Tunis) before
bucketing, because "Thursday 8pm" only means anything in the client's local time.
Each post contributes its primary engagement rate (ERR when reach exists, else ERF,
the same basis logic as the KPI engine) to three groupings: the
(day-of-week x hour) cell, the day-of-week marginal, and the hour marginal. Cells
are ranked by the shrunk score and only surfaced when `n >= 2`. Because cells are
sparse, the day and hour marginals aggregate more data per bucket and are the more
robust guidance; all three are returned.

### 4.4 Content type and hashtags

Both reduce to ranking categories by shrunk engagement rate. For content type the
category is the post's `content_type`; for hashtags each post contributes its ER to
every unique hashtag it used (extracted with a Unicode-aware rule, so Arabic tags
like `#نجاح` count), and a hashtag's `n` is the number of posts that used it. The
same evidence and shrinkage apply.

### 4.5 Honesty and persistence

Not enough data returns a stable `reason` (`insufficient_data`,
`no_engagement_signal`, `no_hashtags`), never a fabricated pick, mirroring the KPI
null-with-reason rule. Every generated recommendation is written to the
`recommendations` table (`kind`, `payload`, `confidence`, `evidence`) so the
dashboard has an auditable history of what was advised and on what basis. The API
routes commit; the service layer only stages rows (the project transaction
convention). All ranking and evidence math in `recommend.py` is unit-tested against
hand-computed fixtures.

## 5. LLM gateway and content generation (Week 6)

The generation features run on free-tier LLM providers (Groq, Gemini, OpenRouter,
NVIDIA NIM, and a local Ollama). No single free tier is reliable enough to depend
on, so the gateway is built around failover rather than a single provider.

### 5.1 Failover chain

A litellm model string encodes its provider: `groq/llama-3.3-70b-versatile`,
`gemini/gemini-2.5-flash`, `openrouter/...`. The gateway builds a chain from
`LLM_PRIMARY`, `LLM_LONGCTX`, and any `LLM_FALLBACKS`, then drops every model whose
provider key is not set and de-duplicates while preserving order. So the chain only
ever contains models that can actually be called, in preference order. On a request
it tries each in turn and returns the first success; if all fail it raises rather
than inventing an answer.

litellm is injected into the gateway and imported lazily. Importing the module
costs nothing, the whole failover loop is unit-tested with a fake completion
function (no network), and the app boots even without the `llm` extra installed
(the endpoint then returns 503 with an install hint, exactly like the sentiment
model without the `nlp` extra).

### 5.2 Observability

Every attempt is timed and recorded, and the service writes one `llm_calls` row per
attempt (`provider`, `model`, `purpose`, token counts, `latency_ms`, `status`,
`fallback_depth`). A failover is therefore visible in the table: a failed row at
depth 0 followed by an ok row at depth 1. Successful responses are cached in Redis
for an hour, keyed by a hash of the messages and parameters; the cache is optional
and degrades silently, like the KPI cache.

### 5.3 Caption generation

`POST /llm/generate` turns a brief into N caption options. The prompt asks for a
JSON array of strings, but models are inconsistent, so the parser tries several
shapes in turn: a raw JSON array, a fenced ```json block, a `{"variants": [...]}`
object, and finally a numbered or bulleted list. It de-duplicates, trims to N, and
never raises on a malformed reply. When an `account_id` is given, the account's most
recent captions are passed to the model as a brand-voice reference. Each result is
stored in `generated_contents` (`request`, `variants`, `provider`, `model`,
`latency_ms`). `GET /llm/providers` reports which providers are configured and the
resulting chain, without leaking any key.

## 6. Analyst agent (Week 7)

An agent that answers questions like "how did engagement do last month?" or "when
should we post?" by calling this project's own analytics functions as tools, then
writing an answer from what they returned. The design goal is not autonomy, it is
traceability: every number in an answer comes from a tool result, and the trace is
stored so any answer can be audited afterwards.

### 6.1 Tools are the existing tested functions

The ten tools in `agent/tools.py` are thin wrappers over code that is already
unit-tested and already serves the API: KPI overview, timeseries, top posts,
platform comparison, sentiment summary, negative alerts, the three recommendation
kinds, and an account list. The agent therefore cannot compute a number a different
way than the dashboard does; it can only ask the same questions the API answers.

Three safety properties are enforced in the registry rather than trusted to the
prompt, because a prompt is not a control:

- **Read-only.** No tool writes. The recommendation tools are invoked with
  `persist=False`, so asking a question never leaves rows behind.
- **Bounded.** Arguments are coerced and clamped: list limits are capped at 20 and
  a window string is validated by the KPI parser, falling back to a default rather
  than raising. A malformed model argument cannot become an unbounded query.
- **Non-fatal.** A tool failure returns `{"error": ...}` for the model to read and
  report. A bad tool call degrades the answer; it never becomes a 500.

### 6.2 The loop

LangGraph orchestrates three nodes:

```
START -> think -> tool calls? -> act -> think -> ...
               -> no tool calls -> END
               -> budget spent  -> finalize -> END
```

`think` asks the model what to do next (with the tool schemas attached), `act`
runs whatever it asked for and feeds the results back as tool messages, and
`finalize` forces a written answer once the budget is gone. The budget is **6 tool
calls** (the cap the data dictionary specifies for `tool_call_count`), with the
graph's `recursion_limit` as a second guard, so a question is bounded in cost and
latency even if the model would otherwise keep calling tools forever.

The node functions are plain functions over a state dict and the gateway is
injected, so the loop's behavior is unit-tested without LangGraph, without a
network, and without a database. LangGraph itself is imported lazily, so the app
boots without the `agent` extra (the endpoint returns 503 with an install hint).

### 6.3 Grounding rules

The system prompt states the rules that make the answer trustworthy: never state a
number that did not come from a tool; report a null-with-reason as unavailable and
say why, never as a zero; pass on a recommendation's evidence (n, lift, confidence)
along with the recommendation; and mention when the engagement basis is `erf`
because the platform hides reach. These mirror the honesty rules the rest of the
codebase enforces in code.

### 6.4 Explainability

Every run writes an `agent_runs` row: the question, the final answer, the
`tool_call_count`, and a `reasoning_trace` holding each tool call with its
arguments, whether it succeeded, and its (truncated) result. Each LLM turn also
writes its `llm_calls` rows, so agent traffic appears in the same observability
table as everything else. `GET /agent/runs` returns recent runs with their traces.

## 7. Topic modeling and retention (Week 8)

### 7.1 Topics

Sentiment says how people feel; topics say what they are talking about. Comments
for an account and window are cleaned with the same `preprocess` the sentiment
model uses (so both describe the same text), clustered, and each cluster is stored
as a `topics` row with its keywords, size, and average sentiment. Each clustered
comment's `comment_analyses.topic_id` is set, so "which subject are people
unhappy about" becomes a join rather than a second model run.

Design choices worth stating:

- Clustering sits behind a `TopicBackend` Protocol, the same pattern as sentiment.
  The pipeline is unit-tested with a deterministic stub, so persistence,
  idempotency and the sentiment rollup are verified without the heavy library.
- Labels are built deterministically from the top keywords, not generated by an
  LLM. A topic whose name changes between runs makes trends impossible to follow;
  an LLM naming pass can be layered on later without changing the contract.
- Below 20 comments in the window the service returns `insufficient_data` instead
  of clustering noise into invented themes. Clusters smaller than `min_topic_size`
  and BERTopic's outlier bucket (`-1`) are never presented as topics.
- Re-running for the same account and window replaces that window's rows, so the
  job is idempotent.

BERTopic is an optional `topics` extra and is **not** installed in the application
image. It pulls umap-learn and hdbscan, which require numba, which caps numpy
below 2.1, while the KPI engine pins numpy 2.2.1. Downgrading numpy to satisfy a
topic model would put the whole analytics layer at risk for a secondary feature,
so instead the endpoints ship, are tested, and answer 503 with an install hint
when the extra is absent, exactly as the sentiment endpoints do without `nlp`.

### 7.2 Retention

`raw_events` archives every API payload so an ingestion bug can be diagnosed and
reprocessed, which means it grows without bound. The brief caps it at 30 days, and
a daily Celery job deletes anything older. The retention window is a parameter with
a documented default rather than a hardcoded constant, and the purge returns what
it deleted, what remains, and the oldest surviving row, so a scheduled job leaves
evidence that it ran instead of being invisible.
