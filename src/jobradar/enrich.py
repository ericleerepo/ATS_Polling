"""Layer 2 — deterministic annotation: keyword score, comp, new-grad signals."""

import re

from .config import Company
from .filters import FilterResult
from .model import Annotations, Posting

# Presence-scored (each keyword counts once). Patterns are prefix-open where
# the family of forms should count (eval/evals/evaluation).
KEYWORDS_HIGH = {
    "llm": r"\bllms?\b",
    "evals": r"\beval",
    "rag": r"\brag\b|retrieval[ -]augmented",
    "fine-tuning": r"fine[ -]?tun",
    "prompt": r"\bprompt",
    "claude": r"\bclaude\b",
    "anthropic": r"\banthropic\b",
    "gpt": r"\bgpt",
    "vertex": r"\bvertex\b",
    "forward deployed": r"forward[ -]deployed",
    "speech-to-text": r"speech[ -]to[ -]text|\bstt\b|transcription",
    "voice": r"\bvoice\b",
    "streaming": r"\bstreaming\b",
    "clinical": r"\bclinical",
    "health": r"\bhealth",
    "patient": r"\bpatient",
    "medical": r"\bmedical\b",
}
KEYWORDS_MEDIUM = {
    "python": r"\bpython\b",
    "typescript": r"\btypescript\b",
    "gcp": r"\bgcp\b|google cloud",
    "terraform": r"\bterraform\b",
    "postgresql": r"\bpostgres",
    "playwright": r"\bplaywright\b",
    "production": r"\bproduction\b",
    "full stack": r"full[ -]?stack",
}
HIGH_WEIGHT = 3.0
MEDIUM_WEIGHT = 1.0

NEW_GRAD = re.compile(
    r"new[ -]grad|entry[ -]level|early[ -]career|0[-–]2 years|recent graduate"
    r"|university grad|early in your career",
    re.I,
)

# "$170,000 - $220,000" and "$170K–$220K" style ranges.
COMP_RANGE = re.compile(
    r"\$\s*(\d{2,3})(?:[,.](\d{3}))?\s*([kK])?\s*(?:-|–|—|to)\s*\$?\s*(\d{2,3})(?:[,.](\d{3}))?\s*([kK])?"
)


def keyword_score(text: str) -> float:
    t = text.lower()
    score = sum(HIGH_WEIGHT for p in KEYWORDS_HIGH.values() if re.search(p, t))
    score += sum(MEDIUM_WEIGHT for p in KEYWORDS_MEDIUM.values() if re.search(p, t))
    return score


def keyword_hits(text: str) -> list[str]:
    """Named hits, high-weight first — shown to the LLM as a feature."""
    t = text.lower()
    hits = [name for name, p in KEYWORDS_HIGH.items() if re.search(p, t)]
    hits += [name for name, p in KEYWORDS_MEDIUM.items() if re.search(p, t)]
    return hits


def extract_comp(text: str) -> tuple[int | None, int | None, str | None]:
    m = COMP_RANGE.search(text)
    if not m:
        return None, None, None

    def value(whole: str, thousands: str | None, k: str | None) -> int:
        if thousands:
            return int(whole) * 1000 + int(thousands)
        if k:
            return int(whole) * 1000
        return int(whole)

    lo = value(m.group(1), m.group(2), m.group(3))
    hi = value(m.group(4), m.group(5), m.group(6))
    if lo < 1000 or hi < 1000 or hi < lo:  # "$50 - $80" hourly noise etc.
        return None, None, None
    return lo, hi, m.group(0).strip()


def annotate(p: Posting, company: Company, fr: FilterResult) -> Annotations:
    """Merge filter flags with enrichment; fills regex comp if unstructured."""
    text = f"{p.title}\n{p.description}"
    if fr.kept and p.comp_min is None:
        p.comp_min, p.comp_max, p.comp_raw = extract_comp(p.description)
    return Annotations(
        filter_result=fr.filter_result,
        senior_flag=fr.senior_flag,
        hybrid_flag=fr.hybrid_flag,
        new_grad_flag=bool(NEW_GRAD.search(text)),
        priority_company=company.priority,
        keyword_score=keyword_score(text) if fr.kept else 0.0,
    )
