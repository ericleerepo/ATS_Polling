import json

import pytest

from jobradar import score
from jobradar.model import Annotations, Posting


def test_parse_scores_roundtrip():
    payload = {
        "scores": [
            {
                "posting_id": 12,
                "skill": 8,
                "odds": 7,
                "growth": 6,
                "story": 9,
                "why": "streaming + clinical overlap",
                "angle": "streaming migration",
            }
        ]
    }
    parsed = score.parse_scores(json.dumps(payload))
    assert parsed[12].composite == round(8 * 0.35 + 7 * 0.35 + 6 * 0.15 + 9 * 0.15, 2)
    assert parsed[12].angle == "streaming migration"


def test_parse_scores_clamps_and_defaults_angle():
    payload = {
        "scores": [
            {
                "posting_id": 1,
                "skill": 14,
                "odds": -2,
                "growth": 5,
                "story": 5,
                "why": "x",
                "angle": "something unexpected",
            }
        ]
    }
    parsed = score.parse_scores(json.dumps(payload))
    assert parsed[1].skill == 10.0 and parsed[1].odds == 0.0
    assert parsed[1].angle == "no strong angle"


def test_parse_scores_rejects_garbage():
    with pytest.raises(Exception):
        score.parse_scores("not json at all")
    with pytest.raises(Exception):
        score.parse_scores('{"wrong": []}')


def test_render_posting_truncates_description():
    p = Posting(
        source="ashby",
        company="Acme",
        external_id="1",
        url="",
        title="AI Engineer",
        location="SF",
        description="LLM evals " * 1000,
    )
    ann = Annotations(filter_result="kept", new_grad_flag=True)
    rendered = score.render_posting(7, p, ann)
    assert rendered["posting_id"] == 7
    assert len(rendered["description"]) <= score.DESCRIPTION_LIMIT
    assert "llm" in rendered["keyword_hits"] and "evals" in rendered["keyword_hits"]
    assert rendered["flags"]["new_grad_signal"] is True


def test_build_system_prompt_includes_few_shot_only_when_present():
    without = score.build_system_prompt("RUBRIC", "PROFILE", "")
    assert "Recent feedback" not in without
    with_examples = score.build_system_prompt("RUBRIC", "PROFILE", "- STRONG MATCH: X")
    assert "Recent feedback" in with_examples and "RUBRIC" in with_examples
