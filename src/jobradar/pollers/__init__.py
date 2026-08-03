"""ATS pollers. Each exposes fetch(Company) -> list[Posting]."""

from . import ashby, getro, greenhouse, lever

POLLERS = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
    "getro": getro.fetch,
}
