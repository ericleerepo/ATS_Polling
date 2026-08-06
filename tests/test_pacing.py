"""Rate-limit pacing and DB round-trip for the backfill path."""

import sqlite3
import time

from jobradar import db, score
from jobradar.model import Annotations, Posting


def test_pacer_enforces_gap_between_requests():
    pacer = score.Pacer(interval=0.05)
    start = time.monotonic()
    for _ in range(3):
        pacer.wait()
    # First call is free; the next two each wait one interval.
    assert time.monotonic() - start >= 0.09


def test_pacer_disabled_when_interval_zero():
    pacer = score.Pacer(interval=0)
    start = time.monotonic()
    for _ in range(5):
        pacer.wait()
    assert time.monotonic() - start < 0.05


def test_retry_delay_uses_api_hint():
    err = Exception(
        "429 RESOURCE_EXHAUSTED {'error': {'details': "
        "[{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '47s'}]}}"
    )
    assert score.retry_delay(err) == 48.0
    assert score.retry_delay(Exception("boom")) == score.MIN_INTERVAL


def test_is_rate_limit_detects_both_shapes():
    coded = Exception("quota")
    coded.code = 429
    assert score.is_rate_limit(coded)
    assert score.is_rate_limit(Exception("429 RESOURCE_EXHAUSTED: quota"))
    assert not score.is_rate_limit(Exception("404 NOT_FOUND"))


# Verbatim shape from the 2026-08-06 backfill log, where splitting the batch
# on this error just spent more of the exhausted request budget.
DAILY_QUOTA_ERROR = Exception(
    "429 RESOURCE_EXHAUSTED {'error': {'details': [{'violations': [{'quotaMetric': "
    "'generativelanguage.googleapis.com/generate_content_free_tier_requests', "
    "'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier', "
    "'quotaValue': '20'}]}]}}"
)
PER_MINUTE_QUOTA_ERROR = Exception(
    "429 RESOURCE_EXHAUSTED {'error': {'details': [{'violations': [{'quotaId': "
    "'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'}]}]}}"
)


def test_daily_quota_distinguished_from_per_minute():
    # Both are 429s, but only the per-minute one is worth splitting or waiting out.
    assert score.is_daily_quota(DAILY_QUOTA_ERROR)
    assert not score.is_daily_quota(PER_MINUTE_QUOTA_ERROR)
    assert score.is_rate_limit(PER_MINUTE_QUOTA_ERROR)
    assert not score.is_daily_quota(Exception("404 NOT_FOUND"))


def test_daily_quota_stops_instead_of_retrying(monkeypatch):
    calls = []

    def fail(*args):
        calls.append("request")
        raise DAILY_QUOTA_ERROR

    monkeypatch.setattr(score, "score_batch", fail)
    monkeypatch.setattr(score.time, "sleep", lambda s: calls.append("slept"))

    result, error, rate_limited, gone = score._attempt_batch(
        None, "m", "sys", [{"posting_id": 1}], score.Pacer(interval=0)
    )

    assert (result, rate_limited, gone) == (None, True, True)
    assert "GenerateRequestsPerDayPerProjectPerModel" in error
    assert calls == ["request"], "must not retry or sleep against a per-day quota"


def make_row(tmp_path) -> sqlite3.Row:
    con = db.connect(tmp_path / "jobs.db")
    p = Posting(
        source="ashby",
        company="Acme",
        external_id="42",
        url="https://x/42",
        title="AI Engineer",
        location="San Francisco",
        description="Build LLM evals.",
        posted_at="2026-08-01T00:00:00+00:00",
        comp_min=150000,
        comp_max=200000,
        comp_raw="$150K–$200K",
    )
    ann = Annotations(
        filter_result="kept",
        senior_flag=True,
        hybrid_flag=False,
        new_grad_flag=True,
        priority_company=True,
        keyword_score=9.0,
    )
    pid = db.insert_posting(con, p, ann)
    return con, pid


def test_row_roundtrip_preserves_posting_and_flags(tmp_path):
    con, pid = make_row(tmp_path)
    row = con.execute("SELECT * FROM postings WHERE id=?", (pid,)).fetchone()
    p = db.posting_from_row(row)
    ann = db.annotations_from_row(row)
    assert (p.title, p.company, p.location) == ("AI Engineer", "Acme", "San Francisco")
    assert (p.comp_min, p.comp_max) == (150000, 200000)
    assert p.description == "Build LLM evals."
    assert ann.kept and ann.new_grad_flag and ann.priority_company and ann.senior_flag
    assert ann.keyword_score == 9.0


def test_unscored_kept_selects_only_unscored_kept_rows(tmp_path):
    con, pid = make_row(tmp_path)
    # A dropped posting and an already-scored one must not be selected.
    db.insert_posting(
        con,
        Posting(source="ashby", company="Acme", external_id="43", url="", title="PM",
                location="SF", description=""),
        Annotations(filter_result="dropped:role"),
    )
    assert [r["id"] for r in db.unscored_kept(con)] == [pid]

    from jobradar.model import Score

    db.record_score(con, pid, Score(8, 8, 8, 8, why="w", angle="puma project"))
    assert db.unscored_kept(con) == []


def test_quota_detail_survives_truncation():
    """The quota id sits deep in the payload — past a naive [:180] cut."""
    err = Exception(
        "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your "
        "current quota, please check your plan and billing details. For more information "
        "on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits.', "
        "'details': [{'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': "
        "[{'quotaMetric': 'generativelanguage.googleapis.com/generate_content_free_tier_requests', "
        "'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier', 'quotaValue': '250'}]}, "
        "{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '32s'}]}}"
    )
    desc = score.describe_error(err, 10)
    assert "PerDay" in desc, desc          # the distinction that matters
    assert "quotaValue=250" in desc
    assert "retryDelay=33s" in desc


def test_describe_error_keeps_non_quota_errors_short():
    desc = score.describe_error(ValueError("x" * 500), 5)
    assert desc.startswith("batch of 5: ValueError:")
    assert len(desc) < 240
