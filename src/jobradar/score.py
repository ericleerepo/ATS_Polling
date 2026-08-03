"""Layer 3 — LLM scoring via the Gemini API.

Postings are batched per call; strict JSON is enforced with a response
schema (response_mime_type=application/json), so parsing never depends on
prompt luck. Any failure degrades to keyword-score ranking (the caller
handles that by leaving Score as None).
"""

import json

from google import genai
from google.genai import types

from .config import Settings
from .enrich import keyword_hits
from .model import Posting, Score

BATCH_SIZE = 8
MAX_TOKENS = 8000
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
) -> tuple[dict[int, Score], list[str]]:
    """Score rendered postings in batches. Returns (scores, errors).

    A failed batch (after one retry) contributes an error string and no
    scores; the caller falls back to keyword rank for those postings.
    """
    client = genai.Client(api_key=settings.gemini_api_key)
    system_prompt = build_system_prompt(rubric, profile, few_shot)
    scores: dict[int, Score] = {}
    errors: list[str] = []
    for i in range(0, len(postings), BATCH_SIZE):
        batch = postings[i : i + BATCH_SIZE]
        last_error = None
        for _attempt in range(2):
            try:
                scores.update(score_batch(client, settings.model, system_prompt, batch))
                last_error = None
                break
            except Exception as e:  # noqa: BLE001 — any failure means keyword fallback
                last_error = f"batch {i // BATCH_SIZE}: {type(e).__name__}: {e}"
        if last_error:
            errors.append(last_error)
    return scores, errors
