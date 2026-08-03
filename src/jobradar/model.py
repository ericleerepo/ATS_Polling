"""Normalized posting shape shared by all pollers, plus pipeline annotations."""

from dataclasses import dataclass


@dataclass
class Posting:
    source: str  # ats key: greenhouse | lever | ashby | getro
    company: str
    external_id: str
    url: str
    title: str
    location: str
    description: str = ""
    posted_at: str | None = None  # ISO 8601 when the ATS provides it
    workplace_type: str | None = None  # remote | hybrid | onsite when structured
    country: str | None = None  # structured country hint (Lever, Ashby)
    comp_min: int | None = None  # whole dollars/year
    comp_max: int | None = None
    comp_raw: str | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.source, self.company, self.external_id)


@dataclass
class Annotations:
    """Layer 1 + Layer 2 results attached to a posting at insert time."""

    filter_result: str  # "kept" or "dropped:<reason>"
    senior_flag: bool = False
    hybrid_flag: bool = False  # data-scientist-at-startup carve-out
    new_grad_flag: bool = False
    priority_company: bool = False
    keyword_score: float = 0.0

    @property
    def kept(self) -> bool:
        return self.filter_result == "kept"


@dataclass
class Score:
    skill: float
    odds: float
    growth: float
    story: float
    why: str
    angle: str  # streaming migration | puma project | no strong angle

    # Composite is computed here, not by the LLM: arithmetic stays deterministic.
    WEIGHTS = {"skill": 0.35, "odds": 0.35, "growth": 0.15, "story": 0.15}

    @property
    def composite(self) -> float:
        w = self.WEIGHTS
        return round(
            self.skill * w["skill"]
            + self.odds * w["odds"]
            + self.growth * w["growth"]
            + self.story * w["story"],
            2,
        )
