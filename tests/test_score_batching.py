"""Batch sizing, adaptive splitting, incremental persistence, and early abort."""

import pytest

from jobradar import score
from jobradar.config import Settings
from jobradar.model import Score


def settings():
    return Settings(
        gemini_api_key="test-key",
        model="test-model",
        gmail_address=None,
        gmail_app_password=None,
        digest_to=None,
    )


def postings(n):
    return [{"posting_id": i, "title": f"Engineer {i}"} for i in range(n)]


def fake_scores(batch):
    return {p["posting_id"]: Score(5, 5, 5, 5, why="w", angle="no strong angle") for p in batch}


class RateLimit(Exception):
    code = 429

    def __str__(self):
        return "429 RESOURCE_EXHAUSTED"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(score.time, "sleep", lambda *_: None)
    monkeypatch.setattr(score.Pacer, "wait", lambda self: None)
    monkeypatch.setattr(score.genai, "Client", lambda **kw: object())


def run(monkeypatch, handler, n, **kw):
    monkeypatch.setattr(score, "score_batch", lambda c, m, s, batch: handler(batch))
    return score.score_all(settings(), "rubric", "profile", "", postings(n), **kw)


def test_output_budget_scales_with_batch():
    assert score.output_budget(1) < score.output_budget(10) < score.output_budget(25)
    assert score.output_budget(10) == score.OUTPUT_TOKENS_BASE + 10 * score.OUTPUT_TOKENS_PER_POSTING


def test_oversized_batch_is_split_not_retried_forever(monkeypatch):
    """Rate limit on a full batch → halve it; the halves succeed."""
    seen = []

    def handler(batch):
        seen.append(len(batch))
        if len(batch) > 5:
            raise RateLimit()
        return fake_scores(batch)

    scores, errors = run(monkeypatch, handler, 10)
    assert len(scores) == 10, "every posting should be scored after splitting"
    assert max(seen) == 10 and min(seen) == 5
    assert any("split batch" in e for e in errors)


def test_scores_persist_per_batch_even_if_a_later_batch_fails(monkeypatch):
    """on_scored fires as each batch lands, so a later abort keeps earlier work."""
    persisted = {}
    calls = {"n": 0}

    def handler(batch):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("boom")
        return fake_scores(batch)

    scores, errors = run(
        monkeypatch, handler, 30, on_scored=lambda s: persisted.update(s)
    )
    assert len(persisted) == score.BATCH_SIZE
    assert persisted.keys() == scores.keys()
    assert errors


def test_aborts_after_consecutive_failures_instead_of_burning_the_clock(monkeypatch):
    """A dead quota should stop the run, not grind through every batch."""
    calls = {"n": 0}

    def handler(batch):
        calls["n"] += 1
        raise RateLimit()

    scores, errors = run(monkeypatch, handler, 200)
    assert scores == {}
    assert any("aborting" in e for e in errors)
    # Batches of MIN_BATCH or smaller are not split further, so the abort
    # counter is what stops it — far short of the 20 batches queued.
    assert calls["n"] < 60, f"made {calls['n']} calls before giving up"


def test_clean_run_scores_everything(monkeypatch):
    scores, errors = run(monkeypatch, fake_scores, 25)
    assert len(scores) == 25 and not errors
