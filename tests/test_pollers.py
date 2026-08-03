"""Poller parsing tests against captured real API responses (tests/fixtures/)."""

import json
from pathlib import Path

from jobradar.config import Company
from jobradar.pollers import ashby, greenhouse, lever

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def test_greenhouse_parse():
    postings = greenhouse.parse(load("greenhouse"), Company("SmarterDx", "greenhouse", "smarterdx"))
    assert len(postings) == 2
    p = postings[0]
    assert p.source == "greenhouse"
    assert p.company == "SmarterDx"
    assert p.title == "Client Support Analyst I"
    assert "Remote (United States)" in p.location
    assert p.posted_at == "2026-07-27T13:48:30-04:00"  # first_published, not updated_at
    assert p.external_id and p.url.startswith("http")
    # content was HTML-escaped HTML; parsed description must be clean text
    assert "<" not in p.description[:500] and len(p.description) > 200


def test_ashby_parse():
    postings = ashby.parse(load("ashby"), Company("OpenEvidence", "ashby", "openevidence"))
    assert len(postings) == 2
    p = postings[0]
    assert p.source == "ashby"
    assert p.title == "Member of Technical Staff"
    assert "San Francisco" in p.location
    assert p.posted_at and p.posted_at.startswith("2026-01-22")
    assert len(p.description) > 100


def test_ashby_skips_unlisted():
    data = load("ashby")
    data["jobs"][0]["isListed"] = False
    postings = ashby.parse(data, Company("OpenEvidence", "ashby", "openevidence"))
    assert len(postings) == 1


def test_ashby_structured_salary():
    comp = {
        "compensationTierSummary": "$150K – $200K • Offers Equity",
        "compensationTiers": [
            {
                "components": [
                    {"compensationType": "Salary", "minValue": 150000, "maxValue": 200000},
                    {"compensationType": "EquityPercentage", "minValue": 0, "maxValue": 1},
                ]
            }
        ],
    }
    assert ashby._salary(comp) == (150000, 200000, "$150K – $200K • Offers Equity")
    assert ashby._salary({}) == (None, None, None)


def test_lever_parse():
    postings = lever.parse(load("lever"), Company("Palantir", "lever", "palantir"))
    assert len(postings) == 2
    p = postings[0]
    assert p.source == "lever"
    assert p.title == "Administrative Business Partner"
    assert "London" in p.location
    assert p.workplace_type == "hybrid"
    assert p.posted_at and p.posted_at.endswith("+00:00")  # epoch-ms converted to ISO UTC
    assert len(p.description) > 100
