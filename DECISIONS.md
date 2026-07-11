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
