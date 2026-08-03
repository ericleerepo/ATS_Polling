import requests

HEADERS = {"User-Agent": "job-radar/0.1 (+https://github.com/eric-lee/job-radar)"}
TIMEOUT = 60


def get_json(url: str):
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()
