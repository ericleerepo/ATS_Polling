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

# Free-tier quotas are per-minute *token* budgets, not just request counts, so
# an oversized batch fails no matter how long you wait for it. 10 postings is
# ~5.8K input tokens; 25 was ~12.6K and got rejected every single time.
BATCH_SIZE = int(os.environ.get("JOBRADAR_BATCH_SIZE", "10"))
MIN_BATCH = 3  # floor for the adaptive split below
MAX_ATTEMPTS = 3
# Reserved output tokens count against that budget, so size them to the batch
# instead of reserving a flat 8K for what is really ~100 tokens per posting.
OUTPUT_TOKENS_PER_POSTING = 150
OUTPUT_TOKENS_BASE = 400
# Pace proactively — waiting between requests costs seconds, tripping the limit
# costs the batch. Set JOBRADAR_MIN_INTERVAL=0 on a paid key to run flat out.
MIN_INTERVAL = float(os.environ.get("JOBRADAR_MIN_INTERVAL", "13"))
# Stop burning wall-clock once it's clear the quota is gone.
MAX_CONSECUTIVE_FAILURES = 4

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


def quota_detail(error: Exception) -> str:
    """Name the quota that was hit — per-minute and per-day limits need
    completely different responses, and the distinction lives deep in the
    error payload, past where a naive truncation would cut it off."""
    bits = re.findall(r"'(quotaId|quotaMetric|quotaValue)':\s*'([^']*)'", str(error))
    return " ".join(f"{k}={v}" for k, v in bits) or "quota unspecified"


def describe_error(error: Exception, batch_size: int) -> str:
    label = f"batch of {batch_size}: {type(error).__name__}"
    if is_rate_limit(error):
        return f"{label}: 429 [{quota_detail(error)}] retryDelay={retry_delay(error):.0f}s"
    return f"{label}: {str(error)[:180]}"


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


def output_budget(batch_size: int) -> int:
    return OUTPUT_TOKENS_BASE + OUTPUT_TOKENS_PER_POSTING * batch_size


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
            max_output_tokens=output_budget(len(batch)),
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
    on_scored=None,
) -> tuple[dict[int, Score], list[str]]:
    """Score rendered postings in batches. Returns (scores, errors).

    A failed batch (after retries) contributes an error string and no scores;
    the caller falls back to keyword rank for those postings. A batch rejected
    for rate limits is halved and retried, since free-tier quotas are per-minute
    *token* budgets that an oversized request can never satisfy by waiting.

    `progress` is an optional callback(batches_done, batches_total, scores_so_far).
    `on_scored` is called with each batch's scores as soon as they arrive, so
    callers can persist incrementally instead of losing everything to a timeout.
    """
    client = genai.Client(api_key=settings.gemini_api_key)
    system_prompt = build_system_prompt(rubric, profile, few_shot)
    pacer = Pacer()
    scores: dict[int, Score] = {}
    errors: list[str] = []
    queue = [postings[i : i + BATCH_SIZE] for i in range(0, len(postings), BATCH_SIZE)]
    total = len(queue)
    done = 0
    consecutive_failures = 0

    while queue:
        batch = queue.pop(0)
        result, error, rate_limited = _attempt_batch(
            client, settings.model, system_prompt, batch, pacer
        )

        if result is not None:
            scores.update(result)
            if on_scored:
                on_scored(result)  # persist now — a later timeout must not lose this
            consecutive_failures = 0
        elif rate_limited and len(batch) > MIN_BATCH:
            # Oversized for the per-minute token budget: halve it and retry.
            # Waiting cannot help a request that is too big on its own.
            mid = len(batch) // 2
            queue[:0] = [batch[:mid], batch[mid:]]
            total += 1
            errors.append(f"split batch of {len(batch)} after rate limit")
            continue
        else:
            errors.append(error or "unknown failure")
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                errors.append(
                    f"aborting: {consecutive_failures} batches failed in a row "
                    f"({len(queue)} left unscored — quota is likely exhausted)"
                )
                break

        done += 1
        if progress:
            progress(done, total, len(scores))
    return scores, errors


def _attempt_batch(client, model, system_prompt, batch, pacer):
    """Returns (scores | None, error | None, hit_rate_limit)."""
    last_error, rate_limited = None, False
    for attempt in range(MAX_ATTEMPTS):
        pacer.wait()
        try:
            return score_batch(client, model, system_prompt, batch), None, False
        except Exception as e:  # noqa: BLE001 — any failure means keyword fallback
            last_error = describe_error(e, len(batch))
            if is_rate_limit(e):
                rate_limited = True
                if attempt < MAX_ATTEMPTS - 1:
                    time.sleep(retry_delay(e))
            elif attempt >= 1:  # non-rate-limit: one retry, then give up on it
                break
    return None, last_error, rate_limited
