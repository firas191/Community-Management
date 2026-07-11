"""KPI query service (brief Sections 8, 12). The only analytics layer with a DB.

It loads posts joined to their latest metric snapshot, resolves followers, builds
a DataFrame, and delegates all arithmetic to the pure `kpi` and `aggregation`
modules. Every endpoint in `routes_kpi` is a thin wrapper over one function here.

Metric snapshots are append-only (brief 6.2), so "current" metrics for a post are
its most recent snapshot, selected with a per-post MAX(captured_at) join.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.analytics import aggregation as agg
from app.analytics import kpi
from app.analytics.kpi import PostMetrics
from app.models import Account, Platform, Post, PostMetricSnapshot
from config.constants import DISPLAY_TZ_DEFAULT

FOLLOWER_SNAPSHOT_MAX_AGE_DAYS = 7
_WINDOW_RE = re.compile(r"^\s*(\d+)\s*([hdw])\s*$", re.IGNORECASE)
_UNIT_HOURS = {"h": 1, "d": 24, "w": 24 * 7}

# Raw count metrics that map straight to a snapshot column.
_COUNT_COLS = {
    "likes": "likes",
    "comments": "comments",
    "shares": "shares",
    "saves": "saves",
    "reach": "reach",
    "impressions": "impressions",
    "video_views": "video_views",
    "clicks": "clicks",
    "engagement": "engagement",
}
_RATE_ALIASES = {"err", "erf", "engagement_rate", "er"}


class KPIQueryError(ValueError):
    """Bad query input (bad window or metric). Mapped to HTTP 400."""


class AccountNotFoundError(KPIQueryError):
    """Requested account does not exist. Mapped to HTTP 404."""


def parse_window(window: str) -> timedelta:
    """'30d' -> 30 days, '48h' -> 48 hours, '12w' -> 12 weeks."""
    m = _WINDOW_RE.match(window or "")
    if not m:
        raise KPIQueryError(f"Invalid window '{window}'. Use forms like '30d', '48h', '12w'.")
    return timedelta(hours=int(m.group(1)) * _UNIT_HOURS[m.group(2).lower()])


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Follower resolution (see DECISIONS.md refinement for Week 2) ---
def resolve_followers(db: Session, account: Account, at: datetime | None = None) -> tuple[int | None, str]:
    """Followers at a point in time, preferring a snapshot, then the latest count.

    Truth is `follower_snapshots` (brief 6.2). When no snapshot lies within 7 days
    of `at` (for example back-imported posts that predate snapshotting), fall back
    to the account's denormalized latest `followers_count` and label the basis
    'account_latest' so the source is never hidden. Null only when neither exists.
    """
    at = at or _now()
    low, high = at - timedelta(days=FOLLOWER_SNAPSHOT_MAX_AGE_DAYS), at + timedelta(
        days=FOLLOWER_SNAPSHOT_MAX_AGE_DAYS
    )
    from app.models import FollowerSnapshot

    stmt = (
        select(FollowerSnapshot.followers_count)
        .where(
            FollowerSnapshot.account_id == account.id,
            FollowerSnapshot.captured_at >= low,
            FollowerSnapshot.captured_at <= high,
        )
        .order_by(func.abs(func.extract("epoch", FollowerSnapshot.captured_at - at)))
        .limit(1)
    )
    snap = db.scalar(stmt)
    if snap is not None:
        return int(snap), "snapshot"
    if account.followers_count is not None:
        return int(account.followers_count), "account_latest"
    return None, "unavailable"


def _get_account(db: Session, account_id: int) -> Account:
    acc = db.get(Account, account_id)
    if acc is None:
        raise AccountNotFoundError(f"Account {account_id} not found.")
    return acc


def _latest_snapshot_subquery():
    """One row per post: the MAX(captured_at) snapshot key."""
    return (
        select(
            PostMetricSnapshot.post_id.label("post_id"),
            func.max(PostMetricSnapshot.captured_at).label("mx"),
        )
        .group_by(PostMetricSnapshot.post_id)
        .subquery()
    )


def load_posts_df(
    db: Session,
    *,
    account_id: int | None = None,
    platform_id: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    include_synthetic: bool = True,
) -> pd.DataFrame:
    """Posts joined to their latest snapshot as a DataFrame. Followers added per account."""
    latest = _latest_snapshot_subquery()
    snap = PostMetricSnapshot
    stmt = (
        select(
            Post.id.label("post_id"),
            Post.account_id,
            Post.published_at,
            Post.content_type,
            Post.permalink,
            Post.text_content,
            Post.is_synthetic,
            Platform.name.label("platform"),
            snap.likes,
            snap.comments_count.label("comments"),
            snap.shares,
            snap.saves,
            snap.reach,
            snap.impressions,
            snap.video_views,
            snap.clicks,
        )
        .join(latest, latest.c.post_id == Post.id)
        .join(snap, and_(snap.post_id == latest.c.post_id, snap.captured_at == latest.c.mx))
        .join(Account, Account.id == Post.account_id)
        .join(Platform, Platform.id == Account.platform_id)
    )
    if account_id is not None:
        stmt = stmt.where(Post.account_id == account_id)
    if platform_id is not None:
        stmt = stmt.where(Account.platform_id == platform_id)
    if since is not None:
        stmt = stmt.where(Post.published_at >= since)
    if until is not None:
        stmt = stmt.where(Post.published_at < until)
    if not include_synthetic:
        stmt = stmt.where(Post.is_synthetic.is_(False))

    rows = db.execute(stmt).mappings().all()
    cols = [
        "post_id", "account_id", "published_at", "content_type", "permalink",
        "text_content", "is_synthetic", "platform", "likes", "comments", "shares",
        "saves", "reach", "impressions", "video_views", "clicks",
    ]
    df = pd.DataFrame(list(rows), columns=cols)
    if df.empty:
        return df

    for c in ("likes", "comments", "shares", "saves"):
        df[c] = df[c].fillna(0).astype("int64")
    df["engagement"] = df[["likes", "comments", "shares", "saves"]].sum(axis=1)

    # Attach followers per account (resolved once per account, not per row).
    fol: dict[int, int | None] = {}
    for aid in df["account_id"].unique():
        acc = db.get(Account, int(aid))
        fol[int(aid)] = resolve_followers(db, acc)[0] if acc else None
    df["followers"] = df["account_id"].map(fol)
    return df


def _pm_from_row(row: pd.Series) -> PostMetrics:
    def _opt(v: object) -> int | None:
        return None if v is None or (isinstance(v, float) and pd.isna(v)) else int(v)

    return PostMetrics(
        likes=int(row["likes"]),
        comments=int(row["comments"]),
        shares=int(row["shares"]),
        saves=int(row["saves"]),
        reach=_opt(row["reach"]),
        impressions=_opt(row["impressions"]),
        video_views=_opt(row["video_views"]),
        clicks=_opt(row["clicks"]),
        followers=_opt(row["followers"]),
    )


def _primary_er_series(df: pd.DataFrame) -> tuple[list[float], str]:
    """Per-post primary ER values that resolved, plus the dominant basis."""
    values: list[float] = []
    bases: list[str] = []
    for _, row in df.iterrows():
        metric, basis = kpi.primary_engagement_rate(_pm_from_row(row))
        if metric.ok:
            values.append(metric.value)  # type: ignore[arg-type]
            bases.append(basis)
    dominant = max(set(bases), key=bases.count) if bases else "none"
    return values, dominant


def _reach_or_followers_basis(df: pd.DataFrame) -> str:
    """Choose 'reach' when the account exposes it, else 'followers'."""
    if df["reach"].notna().any() and pd.to_numeric(df["reach"], errors="coerce").fillna(0).gt(0).any():
        return "reach"
    return "followers"


# --- Endpoint services ---
def overview(
    db: Session,
    account_id: int,
    window: str = "30d",
    *,
    tz: str = DISPLAY_TZ_DEFAULT,
    include_synthetic: bool = True,
) -> dict:
    """Headline KPIs for an account over a window, with deltas vs the prior window."""
    acc = _get_account(db, account_id)
    delta = parse_window(window)
    now = _now()
    cur_since, prev_since = now - delta, now - 2 * delta

    cur = load_posts_df(db, account_id=account_id, since=cur_since, until=now, include_synthetic=include_synthetic)
    prev = load_posts_df(db, account_id=account_id, since=prev_since, until=cur_since, include_synthetic=include_synthetic)

    cur_er, basis = _primary_er_series(cur)
    prev_er, _ = _primary_er_series(prev)
    followers, fol_basis = resolve_followers(db, acc)

    cur_eng = int(cur["engagement"].sum()) if not cur.empty else 0
    prev_eng = int(prev["engagement"].sum()) if not prev.empty else 0
    window_days = delta.total_seconds() / 86400.0

    best = worst = None
    if cur_er:
        er_rows = [
            (int(r["post_id"]), kpi.primary_engagement_rate(_pm_from_row(r))[0].value, r.get("permalink"))
            for _, r in cur.iterrows()
        ]
        er_rows = [t for t in er_rows if t[1] is not None]
        if er_rows:
            best_t = max(er_rows, key=lambda t: t[1])
            worst_t = min(er_rows, key=lambda t: t[1])
            best = {"post_id": best_t[0], "engagement_rate": best_t[1], "permalink": best_t[2]}
            worst = {"post_id": worst_t[0], "engagement_rate": worst_t[1], "permalink": worst_t[2]}

    return {
        "account_id": account_id,
        "handle": acc.handle,
        "platform": db.get(Platform, acc.platform_id).name if acc.platform_id else None,
        "window": window,
        "generated_at": now.isoformat(),
        "engagement_rate_basis": basis,
        "followers": {"value": followers, "basis": fol_basis},
        "n_posts": int(len(cur)),
        "posting_frequency_per_week": kpi.posting_frequency_per_week(len(cur), window_days).as_dict(),
        "total_engagement": cur_eng,
        "avg_engagement_rate": kpi.mean_metric(cur_er).as_dict(),
        "median_engagement_rate": kpi.median_metric(cur_er).as_dict(),
        "posting_consistency_hours": kpi.posting_consistency(
            list(pd.to_datetime(cur["published_at"], utc=True)) if not cur.empty else []
        ).as_dict(),
        "deltas": {
            "total_engagement_pct": kpi.delta_pct(cur_eng, prev_eng).as_dict(),
            "avg_engagement_rate_pct": kpi.delta_pct(
                kpi.mean_metric(cur_er).value, kpi.mean_metric(prev_er).value
            ).as_dict(),
            "n_posts_pct": kpi.delta_pct(len(cur), len(prev)).as_dict(),
        },
        "best_post": best,
        "worst_post": worst,
    }


def timeseries(
    db: Session,
    account_id: int,
    metric: str = "err",
    granularity: str = "day",
    *,
    dt_from: datetime | None = None,
    dt_to: datetime | None = None,
    tz: str = DISPLAY_TZ_DEFAULT,
    include_synthetic: bool = True,
    rolling: int | None = None,
) -> dict:
    """Any metric over time, chart-ready and gap-filled (brief 7.3, 8.3)."""
    _get_account(db, account_id)
    now = _now()
    dt_to = dt_to or now
    dt_from = dt_from or (dt_to - timedelta(days=30))
    df = load_posts_df(db, account_id=account_id, since=dt_from, until=dt_to, include_synthetic=include_synthetic)

    metric_l = metric.lower()
    if metric_l in _RATE_ALIASES:
        denom = _reach_or_followers_basis(df) if not df.empty else "reach"
        ts = agg.engagement_rate_timeseries(
            df, "published_at", granularity, tz, denom_col=denom, name=f"engagement_rate_by_{denom}"
        )
    elif metric_l in _COUNT_COLS:
        ts = agg.sum_timeseries(df, _COUNT_COLS[metric_l], "published_at", granularity, tz, name=metric_l)
    else:
        raise KPIQueryError(
            f"Unknown metric '{metric}'. Use one of: err, {', '.join(sorted(_COUNT_COLS))}."
        )

    out = ts.as_dict()
    if rolling and out["series"]:
        base = out["series"][0]["data"]
        out["series"].append(
            {"name": f"{out['series'][0]['name']}_rolling_{rolling}", "data": agg.rolling_mean(base, rolling)}
        )
    out.update({"account_id": account_id, "metric": metric_l, "granularity": granularity})
    return out


def by_platform(
    db: Session,
    window: str = "30d",
    *,
    tz: str = DISPLAY_TZ_DEFAULT,
    include_synthetic: bool = True,
) -> dict:
    """Cross-platform comparison: raw KPIs plus each platform's z-score vs its own
    trailing 90-day baseline (brief Section 8.4). The z-score is the honest answer."""
    delta = parse_window(window)
    now = _now()
    cur_since = now - delta
    baseline_since = now - timedelta(days=90)

    rows = []
    for plat in db.scalars(select(Platform)).all():
        cur = load_posts_df(db, platform_id=plat.id, since=cur_since, until=now, include_synthetic=include_synthetic)
        if cur.empty:
            continue
        cur_er, basis = _primary_er_series(cur)
        cur_mean = kpi.mean_metric(cur_er)

        # Daily mean ER over the trailing 90 days = the platform's own baseline.
        base_df = load_posts_df(db, platform_id=plat.id, since=baseline_since, until=now, include_synthetic=include_synthetic)
        daily_baseline: list[float] = []
        if not base_df.empty:
            base_df = base_df.copy()
            base_df["day"] = pd.to_datetime(base_df["published_at"], utc=True).dt.date
            for _, g in base_df.groupby("day"):
                vals, _ = _primary_er_series(g)
                if vals:
                    daily_baseline.append(kpi.mean_metric(vals).value)  # type: ignore[arg-type]

        rows.append(
            {
                "platform": plat.name,
                "n_posts": int(len(cur)),
                "engagement_rate_basis": basis,
                "avg_engagement_rate": cur_mean.as_dict(),
                "median_engagement_rate": kpi.median_metric(cur_er).as_dict(),
                "total_engagement": int(cur["engagement"].sum()),
                "zscore_vs_90d_baseline": agg.zscore(cur_mean.value, daily_baseline).as_dict(),
            }
        )
    return {
        "window": window,
        "generated_at": now.isoformat(),
        "note": "Raw ER is not comparable across platforms; the z-score is each platform vs its own 90-day baseline.",
        "platforms": rows,
    }


def top_posts(
    db: Session,
    account_id: int,
    metric: str = "err",
    limit: int = 10,
    *,
    window: str | None = None,
    include_synthetic: bool = True,
) -> dict:
    """Top posts ranked by a metric, each with a full KPI breakdown."""
    _get_account(db, account_id)
    since = None
    if window:
        since = _now() - parse_window(window)
    df = load_posts_df(db, account_id=account_id, since=since, include_synthetic=include_synthetic)

    metric_l = metric.lower()
    scored: list[tuple[float, dict]] = []
    for _, row in df.iterrows():
        pm = _pm_from_row(row)
        if metric_l in _RATE_ALIASES:
            score_metric, basis = kpi.primary_engagement_rate(pm)
            score = score_metric.value
        elif metric_l in _COUNT_COLS:
            score = float(row[_COUNT_COLS[metric_l]]) if metric_l != "engagement" else float(pm.engagement)
            basis = metric_l
        else:
            raise KPIQueryError(f"Unknown metric '{metric}'.")
        if score is None:
            continue
        post_kpis = {k: v.as_dict() for k, v in kpi.compute_post_kpis(pm).items()}
        scored.append(
            (
                score,
                {
                    "post_id": int(row["post_id"]),
                    "published_at": pd.to_datetime(row["published_at"], utc=True).isoformat(),
                    "content_type": row["content_type"],
                    "permalink": row["permalink"],
                    "score": round(float(score), 2),
                    "score_basis": basis,
                    "engagement": int(pm.engagement),
                    "kpis": post_kpis,
                },
            )
        )
    scored.sort(key=lambda t: t[0], reverse=True)
    return {
        "account_id": account_id,
        "metric": metric_l,
        "limit": limit,
        "count": min(limit, len(scored)),
        "posts": [item for _, item in scored[:limit]],
    }
