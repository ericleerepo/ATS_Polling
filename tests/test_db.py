import sqlite3

from jobradar import db
from jobradar.model import Annotations, Posting, Score


def make_posting(external_id="1", **overrides) -> Posting:
    defaults = dict(
        source="greenhouse",
        company="Acme",
        external_id=external_id,
        url="https://example.com/1",
        title="Software Engineer",
        location="San Francisco",
        description="Build things with Python.",
        posted_at="2026-08-01T00:00:00+00:00",
    )
    defaults.update(overrides)
    return Posting(**defaults)


def test_diff_is_idempotent(tmp_path):
    con = db.connect(tmp_path / "jobs.db")
    p = make_posting()
    assert p.key not in db.seen_keys(con)
    db.insert_posting(con, p, Annotations(filter_result="kept"))
    assert p.key in db.seen_keys(con)
    # A second poll of the same posting is not "new".
    assert p.key in db.seen_keys(con)


def test_duplicate_insert_rejected(tmp_path):
    con = db.connect(tmp_path / "jobs.db")
    p = make_posting()
    db.insert_posting(con, p, Annotations(filter_result="kept"))
    try:
        db.insert_posting(con, p, Annotations(filter_result="kept"))
        assert False, "expected IntegrityError"
    except sqlite3.IntegrityError:
        pass


def test_dropped_postings_store_no_description(tmp_path):
    con = db.connect(tmp_path / "jobs.db")
    pid = db.insert_posting(
        con, make_posting(), Annotations(filter_result="dropped:seniority")
    )
    row = con.execute("SELECT * FROM postings WHERE id=?", (pid,)).fetchone()
    assert row["description"] is None
    assert row["filter_result"] == "dropped:seniority"


def test_score_roundtrip_and_composite(tmp_path):
    con = db.connect(tmp_path / "jobs.db")
    pid = db.insert_posting(con, make_posting(), Annotations(filter_result="kept"))
    s = Score(skill=8, odds=6, growth=7, story=5, why="strong overlap", angle="puma project")
    db.record_score(con, pid, s)
    row = con.execute("SELECT * FROM postings WHERE id=?", (pid,)).fetchone()
    assert row["llm_composite"] == round(8 * 0.35 + 6 * 0.35 + 7 * 0.15 + 5 * 0.15, 2)
    assert row["llm_angle"] == "puma project"


def test_feedback_roundtrip(tmp_path):
    con = db.connect(tmp_path / "jobs.db")
    pid = db.insert_posting(con, make_posting(), Annotations(filter_result="kept"))
    assert db.apply_feedback(con, pid, +1)
    assert not db.apply_feedback(con, 9999, -1)  # unknown id
    rows = db.recent_feedback(con)
    assert len(rows) == 1 and rows[0]["feedback"] == 1
