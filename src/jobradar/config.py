"""Config: companies.yaml, profile files, and environment settings.

Paths are repo-root-relative; both local runs and the Actions workflow execute
from the repo root.
"""

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("JOBRADAR_ROOT", "."))
COMPANIES_PATH = ROOT / "config" / "companies.yaml"
PROFILE_PATH = ROOT / "profile.md"
PROMPT_PATH = ROOT / "prompts" / "scoring_prompt.md"
FEEDBACK_PATH = ROOT / "feedback.txt"
DB_PATH = ROOT / "data" / "jobs.db"

# profile.md ships with this marker; until the owner replaces it with a real
# profile, LLM scoring is skipped and the digest ranks by keyword score.
PROFILE_PLACEHOLDER_MARKER = "<!-- PLACEHOLDER -->"

DEFAULT_MODEL = "claude-sonnet-5"


@dataclass
class Company:
    name: str
    ats: str  # greenhouse | lever | ashby | getro
    token: str
    priority: bool = False


def load_companies(path: Path = COMPANIES_PATH) -> list[Company]:
    raw = yaml.safe_load(path.read_text())
    return [
        Company(
            name=c["name"],
            ats=c["ats"],
            token=c["token"],
            priority=bool(c.get("priority", False)),
        )
        for c in raw["companies"]
    ]


def load_profile(path: Path = PROFILE_PATH) -> str | None:
    """Return the profile text, or None if it's missing or still the placeholder."""
    if not path.exists():
        return None
    text = path.read_text()
    if PROFILE_PLACEHOLDER_MARKER in text:
        return None
    return text


@dataclass
class Settings:
    anthropic_api_key: str | None
    model: str
    gmail_address: str | None
    gmail_app_password: str | None
    digest_to: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        gmail = os.environ.get("GMAIL_ADDRESS")
        return cls(
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
            model=os.environ.get("JOBRADAR_MODEL", DEFAULT_MODEL),
            gmail_address=gmail,
            gmail_app_password=os.environ.get("GMAIL_APP_PASSWORD"),
            digest_to=os.environ.get("DIGEST_TO") or gmail,  # "" (unset secret) falls back too
        )
