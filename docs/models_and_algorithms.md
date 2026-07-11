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

## 3. Fine-tuned Arabizi model (Week 4)

Reserved. The TUNIZI fine-tuning protocol and per-language evaluation tables
(macro-F1 for fr/en/ar/aeb-latn, before and after) are documented here when that
work lands.
