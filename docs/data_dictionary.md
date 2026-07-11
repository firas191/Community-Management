# Data Dictionary

Every table in the Community Management schema, its columns, and why the column exists. This
mirrors `app/models/` and the initial Alembic migration. Tables listed as
"populated from Week N" exist now so migrations are stable, and fill with data
when their feature lands.

## platforms

Lookup of supported networks. Seeded at migration time with facebook,
instagram, youtube, tiktok, linkedin, x.

| Column | Type | Notes |
|---|---|---|
| id | smallserial | Primary key |
| name | text | Unique platform name |

## accounts

One row per tracked account or page.

| Column | Type | Notes |
|---|---|---|
| id | bigserial | Primary key |
| platform_id | smallint | References platforms |
| external_id | text | Platform-native id |
| handle | text | Username |
| display_name | text | Human name |
| followers_count | int | Denormalized latest value only. Truth is follower_snapshots |
| is_competitor | bool | Enables the benchmarking module |
| created_at | timestamptz | Row creation |

Unique on (platform_id, external_id).

## follower_snapshots

Time series of follower counts. Source of truth for growth-rate KPIs.

| Column | Type | Notes |
|---|---|---|
| account_id | bigint | References accounts, part of key |
| captured_at | timestamptz | Part of key |
| followers_count | int | Count at capture time |

## posts

One row per post. Populated by the CSV importer now, by live connectors from
Week 3.

| Column | Type | Notes |
|---|---|---|
| id | bigserial | Primary key |
| account_id | bigint | References accounts |
| external_id | text | Platform-native post id |
| published_at | timestamptz | Stored in UTC |
| content_type | text | Canonical: photo, video, reel, carousel, text, link, short |
| text_content | text | Caption or body |
| hashtags | text[] | Extracted at ingestion, GIN indexed |
| media_count | smallint | Number of media items |
| permalink | text | Public URL |
| is_synthetic | bool | True only for dev fixtures |
| text_embedding | vector(384) | MiniLM embedding, filled from Week 6 for RAG and similarity |

Unique on (account_id, external_id). Indexed on (account_id, published_at).

## post_metric_snapshots

Append-only engagement time series. One row per fetch, never overwritten.
Nullable metrics stay NULL when the platform does not expose them.

| Column | Type | Notes |
|---|---|---|
| id | bigserial | Primary key |
| post_id | bigint | References posts |
| captured_at | timestamptz | Fetch time |
| likes | int | Default 0 |
| comments_count | int | Default 0 |
| shares | int | Default 0 |
| saves | int | Default 0 |
| reach | int | Nullable. Null on public sources |
| impressions | int | Nullable |
| video_views | int | Nullable |
| clicks | int | Nullable |

Unique on (post_id, captured_at).

## comments

One row per comment. Author identity is hashed, never stored raw.

| Column | Type | Notes |
|---|---|---|
| id | bigserial | Primary key |
| post_id | bigint | References posts |
| external_id | text | Platform-native comment id |
| author_hash | text | SHA-256 of author id |
| text_content | text | Comment body |
| published_at | timestamptz | Comment time |
| like_count | int | Default 0 |
| is_synthetic | bool | True only for dev fixtures |

Unique on (post_id, external_id).

## comment_analyses

NLP output per comment. Populated from Week 3.

| Column | Type | Notes |
|---|---|---|
| comment_id | bigint | Primary key, references comments |
| language | text | fr, en, ar, aeb-latn, other |
| sentiment | text | positive, neutral, negative |
| sentiment_score | real | Confidence of predicted class |
| model_name | text | Which model produced the label |
| model_version | text | Model version for reproducibility |
| topic_id | int | BERTopic cluster |
| is_toxic | bool | Optional toxicity flag |
| analyzed_at | timestamptz | Analysis time |

## topics

BERTopic clusters per account per window. Populated from Week 7.

| Column | Type | Notes |
|---|---|---|
| id | serial | Primary key |
| account_id | bigint | References accounts |
| label | text | LLM-generated human label |
| keywords | text[] | Top keywords |
| comment_count | int | Cluster size |
| avg_sentiment | real | Rollup in range minus 1 to 1 |
| window_start | date | Window start |
| window_end | date | Window end |

## recommendations

Structured recommendations with evidence. Populated from Week 5.

| Column | Type | Notes |
|---|---|---|
| id | bigserial | Primary key |
| account_id | bigint | References accounts |
| kind | text | best_time, content_type, hashtags, format |
| payload | jsonb | The recommendation |
| confidence | text | high, medium, low |
| evidence | jsonb | Sample sizes and lift values |
| generated_at | timestamptz | Generation time |

## generated_contents

LLM generation outputs. Populated from Week 6.

| Column | Type | Notes |
|---|---|---|
| id | bigserial | Primary key |
| account_id | bigint | References accounts |
| request | jsonb | Brief given to the LLM |
| variants | jsonb | N generated options |
| provider | text | Provider that served the call |
| model | text | Model id |
| latency_ms | int | Round-trip latency |
| created_at | timestamptz | Creation time |

## llm_calls

Observability of the free-tier gateway. Populated from Week 6.

| Column | Type | Notes |
|---|---|---|
| id | bigserial | Primary key |
| provider | text | groq, gemini, openrouter, nvidia_nim, ollama |
| model | text | Model id |
| purpose | text | caption, reply, report, agent |
| prompt_tokens | int | Input tokens |
| completion_tokens | int | Output tokens |
| latency_ms | int | Round-trip latency |
| status | text | ok, rate_limited, error |
| fallback_depth | smallint | How many providers were tried |
| created_at | timestamptz | Call time |

## raw_events

Raw API payload archive for debuggability and reprocessing. Retention 30 days,
enforced by a purge job from Week 3.

| Column | Type | Notes |
|---|---|---|
| id | bigserial | Primary key |
| source | text | meta, youtube, csv |
| entity_type | text | post, comment, metric |
| external_id | text | Native id if any |
| payload | jsonb | Raw payload |
| captured_at | timestamptz | Archive time, indexed |

## sync_cursors

Per-account, per-source incremental cursor. Prevents full re-fetch.

| Column | Type | Notes |
|---|---|---|
| id | bigserial | Primary key |
| source | text | meta, youtube |
| account_external_id | text | Account cursor scope |
| entity_type | text | posts, comments, metrics |
| cursor_value | timestamptz | Last synced point |
| updated_at | timestamptz | Cursor update time |

Unique on (source, account_external_id, entity_type).

## agent_runs

Analyst agent runs with tool traces for explainability. Populated from Week 7.

| Column | Type | Notes |
|---|---|---|
| id | bigserial | Primary key |
| account_id | bigint | Account context |
| conversation_id | text | Multi-turn grouping |
| question | text | User question |
| answer | text | Final grounded answer |
| reasoning_trace | jsonb | Tool calls and results |
| tool_call_count | smallint | Tools used, capped at 6 |
| created_at | timestamptz | Run time |
