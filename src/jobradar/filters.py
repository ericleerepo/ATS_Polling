"""Layer 1 — binary keep/drop, no LLM. Pure functions; heavily unit-tested.

Ambiguity resolves toward keeping (a false positive costs the LLM a few
tokens; a false negative silently loses a posting forever).
"""

import re
from dataclasses import dataclass

from .model import Posting

ROLE_BUCKETS = {
    "ml_ai": [
        r"machine learning engineer",
        r"\bml\b.{0,20}engineer",
        r"\bai engineer",
        r"applied ai",
        r"applied scientist",
        r"member of technical staff",
    ],
    "swe": [
        r"software engineer",
        r"software developer",
        r"full[ -]?stack",
        r"back[ -]?end",
        r"front[ -]?end",
    ],
    "fde": [
        r"forward[ -]deployed",
        r"solutions engineer",
        r"solutions architect",
        r"deployment strategist",
        r"technical account",
    ],
}

# Hybrid titles kept + flagged for the LLM to judge (spec: often 70% engineering
# at startups). Pure analyst/PM/sales/design/recruiting titles simply match no
# bucket and drop.
HYBRID_TITLES = [r"data scientist", r"\bml\b", r"machine learning"]

SENIORITY_DROP = re.compile(r"\b(staff|principal|director|manager|lead)\b", re.I)
# "Technical Account Manager" is the standard title for the spec's
# "technical account" FDE bucket — the manager-drop would nullify that whole
# bucket, so it's exempt.
SENIORITY_EXEMPT = re.compile(r"technical account", re.I)
SENIOR_FLAG = re.compile(r"\b(senior|sr\.?)\b", re.I)

YEARS_PATTERN = re.compile(r"(\d{1,2})\s*\+?\s*(?:years|yrs)", re.I)

BAY_AREA = re.compile(
    r"san francisco|\bsf\b|bay area|oakland|berkeley|emeryville|south san francisco"
    r"|palo alto|menlo park|mountain view|redwood city|san mateo|foster city"
    r"|burlingame|sunnyvale|santa clara|san jose|cupertino",
    re.I,
)
REMOTE = re.compile(r"\bremote\b", re.I)
US_SIGNAL = re.compile(r"united states|\busa?\b|\bu\.s\.?a?\b|north america|america", re.I)
FOREIGN_SIGNAL = re.compile(
    r"europe|emea|apac|latam|united kingdom|\buk\b|london|canada|toronto|vancouver"
    r"|montreal|india|bangalore|bengaluru|hyderabad|germany|berlin|munich|france"
    r"|paris|australia|sydney|melbourne|singapore|japan|tokyo|brazil|mexico|poland"
    r"|warsaw|netherlands|amsterdam|dublin|ireland|israel|tel aviv|spain|madrid"
    r"|barcelona|switzerland|zurich|sweden|stockholm|estonia|tallinn|china|korea|seoul",
    re.I,
)


@dataclass
class FilterResult:
    kept: bool
    reason: str | None = None  # drop reason when not kept
    bucket: str | None = None
    senior_flag: bool = False
    hybrid_flag: bool = False

    @property
    def filter_result(self) -> str:
        return "kept" if self.kept else f"dropped:{self.reason}"


def match_role(title: str) -> tuple[str | None, bool]:
    """Return (bucket, hybrid_flag)."""
    t = title.lower()
    for bucket, patterns in ROLE_BUCKETS.items():
        if any(re.search(p, t) for p in patterns):
            return bucket, False
    if any(re.search(p, t) for p in HYBRID_TITLES):
        return "hybrid", True
    return None, False


def requires_7plus_years(description: str) -> bool:
    for m in YEARS_PATTERN.finditer(description):
        if int(m.group(1)) < 7:
            continue
        # "3-7 years" is a range whose minimum is what matters — skip matches
        # immediately preceded by a range dash or another number.
        prefix = description[max(0, m.start() - 3) : m.start()].strip()
        if prefix.endswith(("-", "–", "—")) or (prefix and prefix[-1].isdigit()):
            continue
        return True
    return False


def location_ok(p: Posting) -> bool:
    loc = p.location or ""
    if BAY_AREA.search(loc):
        return True
    remote = REMOTE.search(loc) or p.workplace_type == "remote"
    if remote:
        if p.country and p.country.upper() not in ("US", "USA", "UNITED STATES"):
            return False
        if US_SIGNAL.search(loc):
            return True
        # Bare "Remote": keep unless a foreign signal says otherwise.
        return not FOREIGN_SIGNAL.search(loc)
    if not loc and not p.workplace_type:
        return True  # no location data at all — ambiguous, keep
    return False


def apply(p: Posting) -> FilterResult:
    bucket, hybrid = match_role(p.title)
    if bucket is None:
        return FilterResult(kept=False, reason="role")

    if SENIORITY_DROP.search(p.title) and not SENIORITY_EXEMPT.search(p.title):
        return FilterResult(kept=False, reason="seniority:title")
    if requires_7plus_years(p.description):
        return FilterResult(kept=False, reason="seniority:years")

    if not location_ok(p):
        return FilterResult(kept=False, reason="location")

    return FilterResult(
        kept=True,
        bucket=bucket,
        senior_flag=bool(SENIOR_FLAG.search(p.title)),
        hybrid_flag=hybrid,
    )
