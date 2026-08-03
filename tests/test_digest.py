from jobradar import digest
from jobradar.model import Annotations, Posting, Score


def entry(i, title="Engineer", score=None, keyword=0.0, priority=False):
    return digest.Entry(
        id=i,
        posting=Posting(
            source="ashby",
            company=f"Co{i}",
            external_id=str(i),
            url=f"https://jobs.example/{i}",
            title=title,
            location="San Francisco",
            description="",
            comp_min=150000,
            comp_max=200000,
        ),
        ann=Annotations(
            filter_result="kept", keyword_score=keyword, priority_company=priority
        ),
        score=score,
    )


def scored(i, composite_parts=(8, 8, 8, 8), **kw):
    s = Score(*composite_parts, why=f"why {i}", angle="puma project")
    return entry(i, score=s, **kw)


def test_ranked_scores_beat_keywords():
    entries = [entry(1, keyword=99.0), scored(2, (5, 5, 5, 5)), scored(3, (9, 9, 9, 9))]
    ranked = digest.ranked(entries)
    assert [e.id for e in ranked] == [3, 2, 1]  # any LLM score outranks keyword-only


def test_text_digest_structure():
    entries = [scored(i) for i in range(1, 8)]
    text = digest.render_text(entries, "2026-08-02", notes=["heads up"])
    assert "TOP 5" in text
    assert "ALSO NEW (2)" in text
    assert "NOTE: heads up" in text
    assert "why 1" in text
    assert "$150K–$200K" in text
    assert "Wellfound" in text  # manual boards footer
    assert "feedback.txt" in text  # feedback how-to


def test_empty_digest():
    text = digest.render_text([], "2026-08-02")
    assert "No new matching postings" in text
    assert digest.subject([], "2026-08-02").endswith("no new matches")


def test_subject_names_top_entry():
    subj = digest.subject([scored(1), scored(2, (9, 9, 9, 9))], "2026-08-02")
    assert "2 new" in subj and "Co2" in subj


def test_html_digest_renders_badges_and_ids():
    html = digest.render_html([scored(1, priority=True)], "2026-08-02")
    assert "★ priority" in html and "id 1" in html and "https://jobs.example/1" in html
