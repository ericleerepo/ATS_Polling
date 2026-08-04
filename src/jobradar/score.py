"""Layer 3 — LLM scoring via the Gemini API.

Postings are batched per call; strict JSON is enforced with a response
schema (response_mime_type=application/json), so parsing never depends on
prompt luck. Any failure degrades to keyword-score ranking (the caller
handles that by leaving Score as None).
"""

import json
import os
import re
import time

from google import genai
from google.genai import types

from .config import Settings
from .enrich import keyword_hits
from .model import Posting, Score

BATCH_SIZE = 25
MAX_TOKENS = 8000
MAX_ATTEMPTS = 4
# Free-tier keys allow ~5 requests/minute. Pace proactively — waiting between
# requests costs seconds, while tripping the limit costs the whole batch.
# Set JOBRADAR_MIN_INTERVAL=0 on a paid key to run flat out.
MIN_INTERVAL = float(os.environ.get("JOBRADAR_MIN_INTERVAL", "13"))

_RETRY_DELAY = re.compile(r"'retryDelay':\s*'(\d+(?:\.\d+)?)s'")
DESCRIPTION_LIMIT = 1500  # chars of description shown to the model per posting

ANGLES = ["streaming migration", "puma project", "no strong angle"]

# OpenAPI-subset schema (what the Gemini API accepts for response_schema).
SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "posting_id": {"type": "integer"},
                    "skill": {"type": "number"},
                    "odds": {"type": "number"},
                    "growth": {"type": "number"},
                    "story": {"type": "number"},
                    "why": {"type": "string"},
                    "angle": {"type": "string", "enum": ANGLES},
                },
                "required": ["posting_id", "skill", "odds", "growth", "story", "why", "angle"],
            },
        }
    },
    "required": ["scores"],
}


class Pacer:
    """Enforces a minimum gap between requests (monotonic clock)."""

    def __init__(self, interval: float = MIN_INTERVAL):
        self.interval = interval
        self._last: float | None = None

    def wait(self) -> None:
        if self.interval > 0 and self._last is not None:
            remaining = self.interval - (time.monotonic() - self._last)
            if remaining > 0:
                time.sleep(remaining)
        self._last = time.monotonic()


def retry_delay(error: Exception) -> float:
    """Seconds to back off after a rate-limit error, using the API's own hint."""
    m = _RETRY_DELAY.search(str(error))
    return float(m.group(1)) + 1 if m else MIN_INTERVAL


def is_rate_limit(error: Exception) -> bool:
    return getattr(error, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(error)


def build_system_prompt(rubric: str, profile: str, few_shot: str) -> str:
    parts = [
        rubric,
        "# Candidate profile\n\n" + profile,
    ]
    if few_shot:
        parts.append("# Recent feedback from the candidate\n\n" + few_shot)
    parts.append(
        "Score each posting in the user message. Return one entry per posting, "
        "keyed by its posting_id. Subscores are 0-10."
    )
    return "\n\n".join(parts)


def render_posting(posting_id: int, p: Posting, ann) -> dict:
    return {
        "posting_id": posting_id,
        "title": p.title,
        "company": p.company,
        "location": p.location,
        "keyword_hits": keyword_hits(f"{p.title}\n{p.description}"),
        "flags": {
            "new_grad_signal": ann.new_grad_flag,
            "senior_title": ann.senior_flag,
            "hybrid_role": ann.hybrid_flag,
            "priority_company": ann.priority_company,
        },
        "description": p.description[:DESCRIPTION_LIMIT],
    }


def parse_scores(text: str) -> dict[int, Score]:
    data = json.loads(text)
    out = {}
    for s in data["scores"]:
        clamp = lambda v: max(0.0, min(10.0, float(v)))
        out[int(s["posting_id"])] = Score(
            skill=clamp(s["skill"]),
            odds=clamp(s["odds"]),
            growth=clamp(s["growth"]),
            story=clamp(s["story"]),
            why=s["why"],
            angle=s["angle"] if s["angle"] in ANGLES else "no strong angle",
        )
    return out


def score_batch(
    client: genai.Client,
    model: str,
    system_prompt: str,
    batch: list[dict],
) -> dict[int, Score]:
    response = client.models.generate_content(
        model=model,
        contents=json.dumps({"postings": batch}),
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=SCORE_SCHEMA,
            max_output_tokens=MAX_TOKENS,
        ),
    )
    text = response.text
    if not text:  # safety block / truncation — response.text is None or empty
        finish = response.candidates[0].finish_reason if response.candidates else "no candidates"
        raise RuntimeError(f"empty model response ({finish})")
    return parse_scores(text)


def score_all(
    settings: Settings,
    rubric: str,
    profile: str,
    few_shot: str,
    postings: list[dict],
    progress=None,
) -> tuple[dict[int, Score], list[str]]:
    """Score rendered postings in batches. Returns (scores, errors).

    A failed batch (after retries) contributes an error string and no scores;
    the caller falls back to keyword rank for those postings. `progress` is an
    optional callback(batches_done, batches_total, scores_so_far).
    """
    client = genai.Client(api_key=settings.gemini_api_key)
    system_prompt = build_system_prompt(rubric, profile, few_shot)
    pacer = Pacer()
    scores: dict[int, Score] = {}
    errors: list[str] = []
    batches = [postings[i : i + BATCH_SIZE] for i in range(0, len(postings), BATCH_SIZE)]
    for n, batch in enumerate(batches):
        last_error = None
        for attempt in range(MAX_ATTEMPTS):
            pacer.wait()
            try:
                scores.update(score_batch(client, settings.model, system_prompt, batch))
                last_error = None
                break
            except Exception as e:  # noqa: BLE001 — any failure means keyword fallback
                last_error = f"batch {n}: {type(e).__name__}: {str(e)[:200]}"
                if is_rate_limit(e):
                    time.sleep(retry_delay(e))
                elif attempt >= 1:  # non-rate-limit: one retry, then keyword fallback
                    break
        if last_error:
            errors.append(last_error)
        if progress:
            progress(n + 1, len(batches), len(scores))
    return scores, errors
