"""Read-only analytics tools for the agent (brief Section 11.6). No LLM in here.

Each tool is a thin wrapper over a function that is already unit-tested elsewhere
(KPIs, sentiment, recommendations). That is the point: the agent does not
re-implement analysis and cannot invent numbers, it can only call the same code
paths the API serves, and every figure it quotes is therefore reproducible.

Three safety properties, enforced here rather than trusted to the prompt:

1. Read-only. No tool writes, and the recommendation tools are called with
   ``persist=False`` so an agent question never leaves rows behind.
2. Bounded. Arguments are coerced and clamped (limits capped, windows validated),
   so a malformed model argument cannot turn into an unbounded query.
3. Honest. A tool failure is returned as ``{"error": ...}`` for the model to read
   and report, never raised into a 500.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import recommend_service as reco
from app.analytics import service as kpi_service
from app.models import Account, Platform
from app.nlp import service as sentiment_service

MAX_LIMIT = 20


def _window(value: object, default: str = "30d") -> str:
    """Validate a window string via the KPI parser; fall back to the default."""
    w = str(value or default)
    try:
        kpi_service.parse_window(w)
    except kpi_service.KPIQueryError:
        return default
    return w


def _int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _account_id(args: dict, default: int | None) -> int:
    aid = args.get("account_id", default)
    if aid is None:
        raise ValueError("account_id is required and no default account was set for this run.")
    return _int(aid, 0)


# --- tool implementations -------------------------------------------------
def _list_accounts(db: Session, args: dict, default_account: int | None) -> dict:
    rows = db.execute(
        select(Account.id, Account.handle, Account.display_name, Account.followers_count, Platform.name)
        .join(Platform, Platform.id == Account.platform_id)
        .order_by(Account.id)
    ).all()
    return {
        "accounts": [
            {"account_id": r[0], "handle": r[1], "display_name": r[2], "followers": r[3], "platform": r[4]}
            for r in rows
        ]
    }


def _kpi_overview(db: Session, args: dict, default_account: int | None) -> dict:
    return kpi_service.overview(db, _account_id(args, default_account), _window(args.get("window"), "30d"))


def _kpi_timeseries(db: Session, args: dict, default_account: int | None) -> dict:
    return kpi_service.timeseries(
        db,
        _account_id(args, default_account),
        metric=str(args.get("metric") or "err"),
        granularity=str(args.get("granularity") or "day"),
    )


def _kpi_top_posts(db: Session, args: dict, default_account: int | None) -> dict:
    return kpi_service.top_posts(
        db,
        _account_id(args, default_account),
        metric=str(args.get("metric") or "err"),
        limit=min(_int(args.get("limit"), 5), MAX_LIMIT),
        window=_window(args.get("window"), "90d"),
    )


def _kpi_by_platform(db: Session, args: dict, default_account: int | None) -> dict:
    return kpi_service.by_platform(db, _window(args.get("window"), "30d"))


def _sentiment_summary(db: Session, args: dict, default_account: int | None) -> dict:
    return sentiment_service.sentiment_summary(
        db, _account_id(args, default_account), _window(args.get("window"), "30d")
    )


def _sentiment_negative(db: Session, args: dict, default_account: int | None) -> dict:
    return sentiment_service.negative_alerts(
        db,
        _account_id(args, default_account),
        _window(args.get("window"), "14d"),
        min(_int(args.get("limit"), 5), MAX_LIMIT),
    )


def _reco_best_time(db: Session, args: dict, default_account: int | None) -> dict:
    return reco.best_time(
        db, _account_id(args, default_account), _window(args.get("window"), "90d"), persist=False
    )


def _reco_content_types(db: Session, args: dict, default_account: int | None) -> dict:
    return reco.content_types(
        db, _account_id(args, default_account), _window(args.get("window"), "90d"), persist=False
    )


def _reco_hashtags(db: Session, args: dict, default_account: int | None) -> dict:
    return reco.hashtags(
        db, _account_id(args, default_account), _window(args.get("window"), "90d"), persist=False
    )


ToolFn = Callable[[Session, dict, "int | None"], dict]

_ACCOUNT_ARG = {"account_id": {"type": "integer", "description": "Account id. Omit to use the account in context."}}
_WINDOW_ARG = {"window": {"type": "string", "description": "Time window like '7d', '30d', '90d', '12w'."}}

TOOLS: dict[str, dict] = {
    "list_accounts": {
        "fn": _list_accounts,
        "description": "List the accounts available, with their platform and follower count. Use this first if the account is unknown.",
        "properties": {},
    },
    "get_kpi_overview": {
        "fn": _kpi_overview,
        "description": (
            "Headline KPIs for one account over a window: number of posts, total engagement, "
            "average and median engagement rate, posting frequency and consistency, best and "
            "worst post, and deltas versus the previous window."
        ),
        "properties": {**_ACCOUNT_ARG, **_WINDOW_ARG},
    },
    "get_kpi_timeseries": {
        "fn": _kpi_timeseries,
        "description": "A metric over time for one account, gap-filled and chart-ready. Use to explain a rise or drop.",
        "properties": {
            **_ACCOUNT_ARG,
            "metric": {"type": "string", "description": "err, engagement, likes, comments, shares, reach, impressions."},
            "granularity": {"type": "string", "description": "hour, day, week, or month."},
        },
    },
    "get_top_posts": {
        "fn": _kpi_top_posts,
        "description": "Best performing posts for an account, each with its full KPI breakdown and permalink.",
        "properties": {
            **_ACCOUNT_ARG, **_WINDOW_ARG,
            "metric": {"type": "string", "description": "Ranking metric, default err."},
            "limit": {"type": "integer", "description": f"How many posts, max {MAX_LIMIT}."},
        },
    },
    "compare_platforms": {
        "fn": _kpi_by_platform,
        "description": "Compare platforms over a window, including each platform's z-score against its own 90-day baseline.",
        "properties": {**_WINDOW_ARG},
    },
    "get_sentiment_summary": {
        "fn": _sentiment_summary,
        "description": (
            "Comment sentiment for an account: overall distribution, net sentiment, a per-language "
            "breakdown (French, English, Arabic, Tunisian Arabizi), and a daily trend."
        ),
        "properties": {**_ACCOUNT_ARG, **_WINDOW_ARG},
    },
    "get_negative_alerts": {
        "fn": _sentiment_negative,
        "description": "Days with an unusual spike in negative comments, plus recent negative comments themselves.",
        "properties": {
            **_ACCOUNT_ARG, **_WINDOW_ARG,
            "limit": {"type": "integer", "description": f"How many comments, max {MAX_LIMIT}."},
        },
    },
    "recommend_best_time": {
        "fn": _reco_best_time,
        "description": (
            "Best day and hour to post (Africa/Tunis), with day and hour rankings. Each item carries "
            "its evidence: sample size n, lift over the account's baseline, and a confidence tier."
        ),
        "properties": {**_ACCOUNT_ARG, **_WINDOW_ARG},
    },
    "recommend_content_types": {
        "fn": _reco_content_types,
        "description": "Which content types (video, photo, carousel, reel) perform best, with evidence.",
        "properties": {**_ACCOUNT_ARG, **_WINDOW_ARG},
    },
    "recommend_hashtags": {
        "fn": _reco_hashtags,
        "description": "Best performing hashtags by lift over the account's baseline, with evidence.",
        "properties": {**_ACCOUNT_ARG, **_WINDOW_ARG},
    },
}


def tool_schemas() -> list[dict]:
    """The OpenAI/litellm function-calling schema for every tool."""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": spec["description"],
                "parameters": {"type": "object", "properties": spec["properties"], "required": []},
            },
        }
        for name, spec in TOOLS.items()
    ]


def run_tool(db: Session, name: str, arguments: str | dict, default_account: int | None = None) -> dict:
    """Execute one tool by name. Never raises: failures come back as {'error': ...}."""
    spec = TOOLS.get(name)
    if spec is None:
        return {"error": f"Unknown tool '{name}'. Available: {', '.join(sorted(TOOLS))}."}

    if isinstance(arguments, str):
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except (json.JSONDecodeError, ValueError):
            return {"error": f"Arguments for '{name}' were not valid JSON: {arguments[:200]}"}
    else:
        args = dict(arguments or {})
    if not isinstance(args, dict):
        return {"error": f"Arguments for '{name}' must be a JSON object."}

    try:
        return spec["fn"](db, args, default_account)
    except Exception as exc:  # noqa: BLE001 - surfaced to the model, never a 500
        return {"error": f"{type(exc).__name__}: {exc}"}
