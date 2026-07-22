# DECISIONS

Senior-grade choices made where the brief left a detail open. One line of
justification each. No em dashes. Short sentences. Concrete numbers.

## Week 1

- **Named Community Management.** The brief shipped the codename PulseIQ and allowed a rename. The project is named Community Management to match the application it serves. Internal identifiers (Postgres db, Docker project) use the slug `community_management`.
- **Follower count has one honest source.** `follower_snapshots` is truth. `accounts.followers_count` is a denormalized latest-value cache refreshed by the daily snapshot job. KPI code reads snapshots only, never the column.
- **ERF uses nearest follower snapshot within 7 days of publish, else null.** The brief wants followers "at publish time" but snapshots are daily and back-imported posts predate snapshots. No interpolation is presented as truth.
- **Best-time cell metric is configurable: ERR when reach exists, else ERF.** The default data plan (public YouTube) hides reach, so a reach-only best-time engine would return all null. The engine labels which metric it used.
- **SARIMAX is the default forecaster, Prophet is an optional extra.** Prophet drags a compiler toolchain and breaks Docker builds often. The core image must always build (brief: `docker compose up` works every session).
- **Embedding model pinned to paraphrase-multilingual-MiniLM-L12-v2 (384-dim).** One model feeds topics, similarity, and brand-voice RAG. The pgvector(384) column is now load-bearing; changing it later needs a migration.
- **Fine-tuned models load by name or from a `models/` volume, with fallback to Model A.** Checkpoints do not live in git. If Arabizi weights are absent the stack still boots and routes to the multilingual baseline.
- **Raw payloads archived to `raw_events` with a 30-day retention field.** Brief Section 7.1 asks for 30-day archival. A `captured_at` plus a scheduled purge keeps the table bounded.
- **Idempotency via SQLAlchemy `insert().on_conflict_do_update` on the natural keys.** Re-running any ingestion job inserts zero duplicates. Metric snapshots use `on_conflict_do_nothing` because a snapshot at a given instant is immutable.
- **`is_synthetic` defaults to false and is set true only by the synthetic generator.** Every fixture row carries the flag so the API can exclude it. Synthetic data is never shown as real.
- **Division-by-zero in KPIs returns null plus a machine-readable reason, never 0.** A zero lies, a null is honest. Reason strings are stable enums for the dashboard.
- **Timestamps stored in UTC, bucketed in Africa/Tunis.** Storage stays timezone-safe, display matches the client's market.
- **Dependencies are split by roadmap week.** Week 1 installs data + API deps only. transformers, bertopic, litellm, and langgraph arrive in their weeks so the Week 1 image is small and fast to build.
- **CSV snapshots are stamped with an `as_of` capture time, default now.** A CSV export is one fetch. Re-importing the same file with the same `as_of` dedupes on (post_id, captured_at), so re-running never duplicates. A genuinely later export creates a new honest snapshot.
- **CSV naive timestamps are localized to Africa/Tunis then converted to UTC.** Business Suite exports carry local wall-clock time with no offset. This makes stored times correct for a Tunisian client.

## Week 2

- **Follower resolution falls back to the account's latest count, disclosed.** The Week 1 note said ERF uses a snapshot within 7 days else null. In practice no follower snapshot job has run yet and back-imported posts predate snapshots, so a strict null would blank every ERF. The engine now prefers the nearest snapshot within 7 days, else falls back to `accounts.followers_count` labeled `account_latest`, else null. The basis is always returned, so the source is never hidden. Snapshots remain the truth once the daily job exists.
- **Primary engagement rate is ERR when reach exists, else ERF, and the basis is reported.** Public YouTube hides reach, so a reach-only rate would return all null there. Reporting the basis keeps a mixed IG/FB/YouTube feed comparable and honest.
- **Bucket-level engagement rate pools numerator and denominator.** Per bucket the rate is sum(engagement) / sum(reach), not the mean of per-post ratios. A mean of ratios over-weights small posts. This is the standard pooled rate.
- **Temporal bucketing runs in pandas Period space, not date_range.** Mixing `to_period` with `date_range` misaligns weekly and monthly anchors and silently zeroes real buckets. Buckets and the gap-fill range are both Periods of the same frequency. A regression test covers weekly and monthly gap-fill.
- **KPI cache is optional by construction.** Redis caches KPI responses for 15 minutes, but every endpoint computes and serves the answer if Redis is down. Numbers never depend on the cache. Cache read or write failures log a warning and degrade silently.
- **Division-by-zero guard is centralized.** One `_rate` helper enforces the null-with-reason rule for every percentage KPI, so the honesty rule cannot be forgotten in one formula.
- **Latest metric snapshot per post via MAX(captured_at).** Snapshots are append-only, so "current" metrics are the most recent snapshot, selected with a per-post max join. This keeps growth-curve history intact while KPIs use the latest values.

## Week 3

- **The sentiment model sits behind a `SentimentBackend` Protocol, injected.** The real backend lazy-loads cardiffnlp on first use; a stub is injected in tests. This makes the whole pipeline (preprocess, route, classify, store) unit-testable without downloading a 1 GB transformer, and keeps the app booting without the NLP extras.
- **langdetect is a core dependency; transformers + torch are the `nlp` extra.** Language routing (including the Arabizi differentiator) is lightweight and works everywhere. Only real sentiment classification needs the heavy stack, so it is opt-in. Endpoints that need the model return 503 with an install hint, never a 500.
- **The Arabizi rule layer is deterministic and precedes the base detector.** Latin script plus digit-as-letter usage or a curated Tunisian lexicon hit routes to `aeb-latn`. This is the custom, testable core; the base detector (langdetect, fastText-swappable) only handles fr/en. Routing is 9/9 on the seeded registers.
- **Arabizi is classified by Model A in Week 3, flagged `needs_arabizi_specialist`.** The fine-tuned Model B (TUNIZI) lands in Week 4 and replaces that path without changing the interface. The flag keeps provisional labels honest on the dashboard.
- **Comment analysis is idempotent on `comment_id`.** The batch job only pulls comments with no analysis row, and upserts, so re-running never duplicates and a model upgrade can re-label cleanly. Every row stores `model_name` and `model_version`.
- **Sentiment detection runs on raw text, classification on preprocessed text.** Raw text preserves the Arabizi digit-letter signal the router needs; the model gets the cleaned, convention-matched text it was trained on.
- **The Docker image bundles the sentiment stack but downloads the model weights at runtime.** CPU-only torch (~200 MB versus ~2 GB for CUDA) is installed from the PyTorch CPU index before the `nlp` extra so its `torch` pin is already satisfied. Weights are not baked in: baking pushed the image to ~3.5 GB, which overran the Docker data disk on a constrained WSL2 host (snapshot commit I/O error). Instead `HF_HOME=/models/hf` is a named volume shared by api and worker; the model downloads on first use and persists across restarts, keeping the image around 2 GB. The three app services share one built image so it is stored once. CI installs only `.[dev]`, so it stays fast and the real-model smoke test skips there.

## Week 3b (live connectors)

- **Connectors take an injected `get` function, defaulting to the resilient HTTP client.** Same pattern as the sentiment backend: the whole fetch-and-map path is unit-tested with canned API payloads and zero network. Retries (429/5xx with backoff + jitter, Retry-After honored) live in one place, `ingestion/http.py`.
- **YouTube is the primary live source; it needs only an API key.** Public channels require no OAuth, so `docker compose up` plus `YOUTUBE_CHANNEL_IDS` ingests real data. Reach and impressions are owner-private on public channels, so those snapshot fields stay null and reach-based KPIs return null-with-reason.
- **Meta insight metric names are isolated in `INSIGHT_METRICS`.** Graph API renames insight metrics between versions, so a bump is a one-line change, per the brief. Missing insights (permissions, or a post without reach) leave the field null, never 0.
- **Incremental by cursor, never a full re-fetch.** Each account/entity has a row in `sync_cursors`; a run fetches only posts newer than the cursor and advances it. Re-runs are safe because the normalizer upserts and metric snapshots are immutable.
- **Raw API payloads are archived to `raw_events`.** Connectors accumulate the raw items during fetching; the sync runner persists them for debuggability and reprocessing (30-day retention, purge job to follow).
- **The scheduled ingest task skips cleanly when unconfigured.** The Celery `ingest_recent` job runs every 30 minutes but returns early with a log line if the connector has no key or no target ids, so the schedule is safe to enable before credentials exist.
- **The runner does not commit; the caller owns the transaction.** The API route commits (like the CSV path) and the Celery task uses `session_scope`, which commits. This matches the ingestion convention and keeps transaction boundaries at the edges.

## Week 4 (Arabizi fine-tune)

- **Model B is opt-in behind the existing routing layer.** `ARABIZI_MODEL` (a path or HuggingFace id) turns it on; the analyzer then sends only `aeb-latn` text to the specialist and everything else to Model A. Empty means fall back to Model A, flagged `needs_arabizi_specialist`. The inference interface never changes, so training and serving stay decoupled.
- **The fine-tuned model uses Model A's label id order (0=neg, 1=neu, 2=pos).** So the app loads Model B through the same pipeline with no label-mapping change, and both models are interchangeable behind the `SentimentBackend` protocol.
- **Training input is cleaned with the exact inference `preprocess`.** Train/serve skew is a classic silent accuracy killer; reusing one function removes it.
- **Metrics are pure Python, not sklearn.** Macro-F1, per-class, and the per-language table are hand-computed and unit-tested, so the numbers in the report are trustworthy and the training extra stays lighter. Macro-F1 is primary because the classes are imbalanced.
- **Seeded stratified 70/10/20 split.** Same seed and data yield the same split, which is what makes the reported before/after numbers reproducible.
- **Training deps live in a `train` extra, run on a free GPU.** `datasets`, `accelerate`, and `mlflow` are not in the app image; fine-tuning runs on Colab/Kaggle (the base models are 110-270M params, minutes on a T4), and only the resulting weights come back to the app via `ARABIZI_MODEL`.

## Week 5 (recommendation engine)

- **Every recommendation carries n, lift, and confidence.** A ranked list of bare numbers is not actionable or trustworthy. Sample size, lift over the account's own baseline, and a confidence tier travel with every pick, so the dashboard can justify advice instead of asserting it (brief 6.2, 8.5).
- **Groups are ranked by a shrinkage estimate, not the raw mean.** `(sum + K*baseline)/(n+K)` with `K=5` pulls thin groups toward the baseline, so one lucky post cannot win the ranking. This is standard empirical-Bayes shrinkage and needs no per-account tuning. The raw mean is still reported.
- **Confidence tiers are sample-size thresholds: n>=8 high, n>=4 medium, n>=2 low.** Below 2 a group is not surfaced at all. Fixed thresholds in one place keep the rule consistent and tunable.
- **Best-time buckets are formed in Africa/Tunis, not UTC.** "Thursday 8pm" is only meaningful in the client's local time, so publish times are converted before day/hour bucketing. Day and hour marginals are returned alongside cells because cells are sparse and the marginals are the more robust guidance.
- **Recommendations reuse the KPI primary-ER basis (ERR else ERF).** The same honest basis logic drives KPIs and recommendations, so a YouTube account with no reach gets ERF-based advice instead of a column of nulls, and the basis is disclosed.
- **Hashtag credit is per-post, Unicode-aware.** Each post lends its ER to every unique hashtag it used, so a hashtag's `n` is the number of posts using it. The extractor matches Unicode word characters, so Arabic hashtags count.
- **Thin data returns a reason, never a guess.** `insufficient_data`, `no_engagement_signal`, and `no_hashtags` mirror the KPI null-with-reason rule.
- **Recommendations are POST and persisted.** Each call generates and writes a `recommendations` row (kind/payload/confidence/evidence) for an auditable history of what was advised. The route commits; the service only stages rows (the project transaction convention).
