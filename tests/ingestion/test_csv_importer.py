"""CSV importer parsing tests (brief Sections 6.1, 7). No database required.

Golden expectations against a Business Suite-style DataFrame. Verifies header
mapping, timezone conversion, and honest handling of absent metrics (None, not 0).
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.ingestion.csv_importer import CSVImportError, parse_dataframe


def _business_suite_df():
    return pd.DataFrame(
        {
            "Post ID": ["100", "101"],
            "Page ID": ["page_9", "page_9"],
            "Page name": ["Demo Page", "Demo Page"],
            "Publish time": ["2026-07-03 19:30:00", "2026-07-04 08:00:00"],
            "Post type": ["Photo", "Reels"],
            "Title": ["Hello #promo", "Second #food"],
            "Reach": [1000, 500],
            "Reactions": [80, 40],
            "Comments": [10, 5],
            "Shares": [4, 2],
        }
    )


def test_parse_maps_headers_and_builds_records():
    accounts, posts, metrics = parse_dataframe(_business_suite_df(), "meta_business_suite_posts")

    assert len(accounts) == 1
    assert accounts[0].external_id == "page_9"
    assert accounts[0].platform == "facebook"

    assert len(posts) == 2
    assert posts[0].external_id == "100"
    assert posts[0].text_content == "Hello #promo"
    # 19:30 Africa/Tunis (UTC+1) stored as 18:30 UTC.
    assert posts[0].published_at.hour == 18

    assert len(metrics) == 2
    assert metrics[0].likes == 80
    assert metrics[0].comments_count == 10
    assert metrics[0].reach == 1000


def test_absent_metric_is_none_not_zero():
    # No Impressions/Saves columns: those fields must be None, never 0.
    _, _, metrics = parse_dataframe(_business_suite_df(), "meta_business_suite_posts")
    assert metrics[0].impressions is None
    assert metrics[0].saves == 0  # saves is a zero-default engagement count
    assert metrics[0].clicks is None


def test_missing_required_column_raises():
    df = _business_suite_df().drop(columns=["Publish time"])
    with pytest.raises(CSVImportError):
        parse_dataframe(df, "meta_business_suite_posts")


def test_unknown_profile_raises():
    with pytest.raises(KeyError):
        parse_dataframe(_business_suite_df(), "does_not_exist")
