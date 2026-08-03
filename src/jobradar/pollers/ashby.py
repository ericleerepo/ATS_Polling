"""Ashby public job-board API.

Quirks: gives `descriptionPlain` directly (no HTML wrangling) and real
structured compensation under `compensation.compensationTiers[].components`.
Unlisted jobs (`isListed: false`) are skipped.
"""

from ..config import Company
from ..model import Posting
from .common import get_json

API = "https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"


def fetch(company: Company) -> list[Posting]:
    data = get_json(API.format(token=company.token))
    return parse(data, company)


def parse(data: dict, company: Company) -> list[Posting]:
    postings = []
    for job in data.get("jobs", []):
        if not job.get("isListed", True):
            continue
        locations = [job.get("location") or ""]
        locations += [s.get("location", "") for s in job.get("secondaryLocations") or []]
        if job.get("isRemote") and not any("remote" in loc.lower() for loc in locations):
            locations.append("Remote")
        comp_min, comp_max, comp_raw = _salary(job.get("compensation") or {})
        workplace = job.get("workplaceType")
        postings.append(
            Posting(
                source="ashby",
                company=company.name,
                external_id=str(job["id"]),
                url=job.get("jobUrl", ""),
                title=job.get("title", ""),
                location="; ".join(loc for loc in locations if loc),
                description=job.get("descriptionPlain") or "",
                posted_at=job.get("publishedAt"),
                workplace_type=workplace.lower() if workplace else None,
                country=((job.get("address") or {}).get("postalAddress") or {}).get(
                    "addressCountry"
                ),
                comp_min=comp_min,
                comp_max=comp_max,
                comp_raw=comp_raw,
            )
        )
    return postings


def _salary(comp: dict) -> tuple[int | None, int | None, str | None]:
    mins, maxs = [], []
    for tier in comp.get("compensationTiers") or []:
        for component in tier.get("components") or []:
            if component.get("compensationType") == "Salary":
                if component.get("minValue") is not None:
                    mins.append(component["minValue"])
                if component.get("maxValue") is not None:
                    maxs.append(component["maxValue"])
    raw = comp.get("compensationTierSummary") or comp.get("scrapeableCompensationSalarySummary")
    return (min(mins) if mins else None, max(maxs) if maxs else None, raw)
