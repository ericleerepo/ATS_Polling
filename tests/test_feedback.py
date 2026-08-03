from jobradar import db, feedback
from jobradar.model import Annotations, Posting


def make_posting(external_id):
    return Posting(
        source="ashby",
        company="Acme",
        external_id=external_id,
        url="",
        title="Software Engineer",
        location="SF",
        description="d",
    )


def test_ingest_applies_labels_and_clears_file(tmp_path):
    con = db.connect(tmp_path / "jobs.db")
    id1 = db.insert_posting(con, make_posting("1"), Annotations(filter_result="kept"))
    id2 = db.insert_posting(con, make_posting("2"), Annotations(filter_result="kept"))
    f = tmp_path / "feedback.txt"
    f.write_text(f"{id1} +\n{id2} -\n999 +\nnonsense line\n\n")

    applied, bad = feedback.ingest(con, f)
    assert applied == 2
    assert len(bad) == 2  # unknown id + unparseable line
    assert f.read_text() == ""

    rows = {r["id"]: r["feedback"] for r in db.recent_feedback(con)}
    assert rows[id1] == 1 and rows[id2] == -1


def test_ingest_missing_file_is_noop(tmp_path):
    con = db.connect(tmp_path / "jobs.db")
    assert feedback.ingest(con, tmp_path / "absent.txt") == (0, [])


def test_few_shot_rendering(tmp_path):
    con = db.connect(tmp_path / "jobs.db")
    pid = db.insert_posting(con, make_posting("1"), Annotations(filter_result="kept"))
    db.apply_feedback(con, pid, 1)
    text = feedback.few_shot_examples(con)
    assert "STRONG MATCH" in text and "Software Engineer at Acme" in text
    empty_con = db.connect(tmp_path / "empty.db")
    assert feedback.few_shot_examples(empty_con) == ""
