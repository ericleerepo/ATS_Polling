"""Getro-powered portfolio boards (jobs.a16z.com).

Best-effort per spec: the board's main value is discovering companies to add
to companies.yaml, not primary coverage. The search backend rejects plain
HTTP clients, so failures here are logged and never fatal to the run.
"""

import requests

from ..config import Company
from ..model import Posting
from .common import HEADERS, TIMEOUT

API = "https://{token}/api-boards/search-jobs"

BROWSER_HEADERS = {
    **HEADERS,
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://jobs.a16z.com",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
}


def fetch(company: Company) -> list[Posting]:
    resp = requests.post(
        API.format(token=company.token),
        json={"query": {}, "meta": {"size": 500}},
        headers=BROWSER_HEADERS,
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return parse(resp.json(), company)


def parse(data: dict, company: Company) -> list[Posting]:
    postings = []
    for job in data.get("results", {}).get("jobs", []):
        postings.append(
            Posting(
                source="getro",
                company=job.get("organization", {}).get("name") or company.name,
                external_id=str(job.get("id")),
                url=job.get("url", ""),
                title=job.get("title", ""),
                location="; ".join(job.get("locations") or []),
                description="",  # Getro search results carry no description
                posted_at=None,
            )
        )
    return postings
