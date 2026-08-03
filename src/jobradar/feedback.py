"""Feedback loop: ingest feedback.txt labels, build few-shot examples.

feedback.txt lines look like `147 +` or `152 -` (posting id + label).
After ingestion the file is truncated; labels live in the DB.
"""

import re
import sqlite3
from pathlib import Path

from . import db

LINE = re.compile(r"^\s*(\d+)\s*([+-])\s*1?\s*$")


def ingest(con: sqlite3.Connection, path: Path) -> tuple[int, list[str]]:
    """Apply labels from the feedback file; truncate it. Returns (applied, bad_lines)."""
    if not path.exists():
        return 0, []
    applied, bad = 0, []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        m = LINE.match(line)
        if not m:
            bad.append(line)
            continue
        posting_id, label = int(m.group(1)), (1 if m.group(2) == "+" else -1)
        if db.apply_feedback(con, posting_id, label):
            applied += 1
        else:
            bad.append(f"{line} (unknown id)")
    path.write_text("")
    return applied, bad


def few_shot_examples(con: sqlite3.Connection, limit: int = 10) -> str:
    """Render the most recent labels as strong/poor match examples for the prompt."""
    rows = db.recent_feedback(con, limit)
    if not rows:
        return ""
    lines = []
    for r in rows:
        verdict = "STRONG MATCH (would apply)" if r["feedback"] > 0 else "POOR MATCH"
        why = f" — {r['llm_why']}" if r["llm_why"] else ""
        lines.append(f"- {verdict}: {r['title']} at {r['company']}{why}")
    return "\n".join(lines)
