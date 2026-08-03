from jobradar import enrich
from jobradar.config import Company
from jobradar.filters import FilterResult
from jobradar.model import Posting


def test_keyword_score_weights():
    # 3 high-weight (llm, evals, rag) + 1 medium (python)
    assert enrich.keyword_score("Build LLM evals with RAG pipelines in Python") == 10.0


def test_keyword_no_substring_false_positives():
    assert enrich.keyword_score("object storage solutions for programmers") == 0.0


def test_keyword_variants():
    hits = enrich.keyword_hits(
        "fine-tuning GPT-4, prompting, evaluation, speech-to-text, PostgreSQL, google cloud"
    )
    assert {"fine-tuning", "gpt", "prompt", "evals", "speech-to-text", "postgresql", "gcp"} <= set(hits)


def test_comp_extraction():
    assert enrich.extract_comp("pays $170,000 - $220,000 plus equity") == (
        170000,
        220000,
        "$170,000 - $220,000",
    )
    lo, hi, _ = enrich.extract_comp("range: $170K–$220K")
    assert (lo, hi) == (170000, 220000)
    assert enrich.extract_comp("hourly $50 - $80") == (None, None, None)
    assert enrich.extract_comp("no comp mentioned") == (None, None, None)


def test_new_grad_flag_and_priority():
    p = Posting(
        source="ashby",
        company="Acme",
        external_id="1",
        url="",
        title="Software Engineer, New Grad",
        location="San Francisco",
        description="Entry level role. Salary $120,000 - $150,000.",
    )
    ann = enrich.annotate(
        p, Company("Acme", "ashby", "acme", priority=True), FilterResult(kept=True)
    )
    assert ann.new_grad_flag
    assert ann.priority_company
    assert p.comp_min == 120000 and p.comp_max == 150000  # regex fallback fills comp


def test_structured_comp_not_overwritten():
    p = Posting(
        source="ashby",
        company="Acme",
        external_id="1",
        url="",
        title="Engineer",
        location="SF",
        description="Salary $1 - $2",
        comp_min=200000,
        comp_max=250000,
    )
    enrich.annotate(p, Company("Acme", "ashby", "acme"), FilterResult(kept=True))
    assert (p.comp_min, p.comp_max) == (200000, 250000)
