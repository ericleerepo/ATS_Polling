"""Lever public postings API.

Quirks: `createdAt` is epoch milliseconds; description is split across
`descriptionPlain` and `additionalPlain`; `salaryRange` only sometimes present.
"""

from datetime import datetime, timezone

from ..config import Company
from ..model import Posting
from .common import get_json

API = "https://api.lever.co/v0/postings/{token}?mode=json"


def fetch(company: Company) -> list[Posting]:
    data = get_json(API.format(token=company.token))
    return parse(data, company)


def parse(data: list, company: Company) -> list[Posting]:
    postings = []
    for job in data:
        cats = job.get("categories") or {}
        locations = cats.get("allLocations") or [cats.get("location") or ""]
        description = "\n".join(
            part for part in (job.get("descriptionPlain"), job.get("additionalPlain")) if part
        )
        posted_at = None
        if job.get("createdAt"):
            posted_at = datetime.fromtimestamp(
                job["createdAt"] / 1000, tz=timezone.utc
            ).isoformat(timespec="seconds")
        salary = job.get("salaryRange") or {}
        postings.append(
            Posting(
                source="lever",
                company=company.name,
                external_id=str(job["id"]),
                url=job.get("hostedUrl", ""),
                title=job.get("text", ""),
                location="; ".join(loc for loc in locations if loc),
                description=description,
                posted_at=posted_at,
                workplace_type=job.get("workplaceType"),
                country=job.get("country"),
                comp_min=salary.get("min"),
                comp_max=salary.get("max"),
                comp_raw=f"{salary.get('min')}-{salary.get('max')} {salary.get('currency', '')}".strip()
                if salary
                else None,
            )
        )
    return postings
