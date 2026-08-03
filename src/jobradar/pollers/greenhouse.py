"""Greenhouse public board API.

Quirks: `content` is HTML-escaped HTML (unescape, then strip tags);
`first_published` is the true posting date (`updated_at` moves on any edit).
"""

import html

from bs4 import BeautifulSoup

from ..config import Company
from ..model import Posting
from .common import get_json

API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"


def fetch(company: Company) -> list[Posting]:
    data = get_json(API.format(token=company.token))
    return parse(data, company)


def parse(data: dict, company: Company) -> list[Posting]:
    postings = []
    for job in data.get("jobs", []):
        content = html.unescape(job.get("content") or "")
        description = BeautifulSoup(content, "html.parser").get_text(" ", strip=True)
        location = (job.get("location") or {}).get("name", "")
        offices = [o["name"] for o in job.get("offices") or [] if o.get("name")]
        for name in offices:
            if name not in location:
                location = f"{location}; {name}" if location else name
        postings.append(
            Posting(
                source="greenhouse",
                company=company.name,
                external_id=str(job["id"]),
                url=job.get("absolute_url", ""),
                title=job.get("title", ""),
                location=location,
                description=description,
                posted_at=job.get("first_published") or job.get("updated_at"),
            )
        )
    return postings
