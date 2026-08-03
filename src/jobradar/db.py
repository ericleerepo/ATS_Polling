"""SQLite storage. One row per posting ever seen; the diff is `key not in DB`.

Dropped postings keep only title/location/drop-reason (no description) so the
committed DB stays small while the diff never reconsiders them.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .model import Annotations, Posting, Score

SCHEMA = """
CREATE TABLE IF NOT EXISTS postings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    company TEXT NOT NULL,
    external_id TEXT NOT NULL,
    url TEXT,
    title TEXT,
    location TEXT,
    description TEXT,
    posted_at TEXT,
    first_seen_at TEXT NOT NULL,
    comp_min INTEGER,
    comp_max INTEGER,
    comp_raw TEXT,
    keyword_score REAL,
    new_grad_flag INTEGER DEFAULT 0,
    senior_flag INTEGER DEFAULT 0,
    hybrid_flag INTEGER DEFAULT 0,
    priority_company INTEGER DEFAULT 0,
    filter_result TEXT,
    llm_skill REAL,
    llm_odds REAL,
    llm_growth REAL,
    llm_story REAL,
    llm_composite REAL,
    llm_why TEXT,
    llm_angle TEXT,
    llm_error TEXT,
    rank_in_digest INTEGER,
    digest_date TEXT,
    feedback INTEGER,
    feedback_at TEXT,
    UNIQUE (source, company, external_id)
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    fetched INTEGER,
    new INTEGER,
    kept INTEGER,
    scored INTEGER,
    emailed INTEGER,
    notes TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def seen_keys(con: sqlite3.Connection) -> set[tuple[str, str, str]]:
    rows = con.execute("SELECT source, company, external_id FROM postings")
    return {(r["source"], r["company"], r["external_id"]) for r in rows}


def insert_posting(con: sqlite3.Connection, p: Posting, ann: Annotations) -> int:
    cur = con.execute(
        """
        INSERT INTO postings (
            source, company, external_id, url, title, location, description,
            posted_at, first_seen_at, comp_min, comp_max, comp_raw,
            keyword_score, new_grad_flag, senior_flag, hybrid_flag,
            priority_company, filter_result
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            p.source,
            p.company,
            p.external_id,
            p.url,
            p.title,
            p.location,
            p.description if ann.kept else None,
            p.posted_at,
            now_iso(),
            p.comp_min,
            p.comp_max,
            p.comp_raw,
            ann.keyword_score,
            int(ann.new_grad_flag),
            int(ann.senior_flag),
            int(ann.hybrid_flag),
            int(ann.priority_company),
            ann.filter_result,
        ),
    )
    return cur.lastrowid


def record_score(con: sqlite3.Connection, posting_id: int, s: Score) -> None:
    con.execute(
        """
        UPDATE postings SET llm_skill=?, llm_odds=?, llm_growth=?, llm_story=?,
               llm_composite=?, llm_why=?, llm_angle=?, llm_error=NULL
        WHERE id=?
        """,
        (s.skill, s.odds, s.growth, s.story, s.composite, s.why, s.angle, posting_id),
    )


def record_score_error(con: sqlite3.Connection, posting_id: int, error: str) -> None:
    con.execute("UPDATE postings SET llm_error=? WHERE id=?", (error, posting_id))


def mark_digest(con: sqlite3.Connection, ranked_ids: list[int], digest_date: str) -> None:
    for rank, posting_id in enumerate(ranked_ids, start=1):
        con.execute(
            "UPDATE postings SET rank_in_digest=?, digest_date=? WHERE id=?",
            (rank, digest_date, posting_id),
        )


def apply_feedback(con: sqlite3.Connection, posting_id: int, label: int) -> bool:
    cur = con.execute(
        "UPDATE postings SET feedback=?, feedback_at=? WHERE id=?",
        (label, now_iso(), posting_id),
    )
    return cur.rowcount > 0


def recent_feedback(con: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT id, title, company, llm_why, keyword_score, feedback
        FROM postings WHERE feedback IS NOT NULL
        ORDER BY feedback_at DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()


def record_run(
    con: sqlite3.Connection,
    *,
    fetched: int,
    new: int,
    kept: int,
    scored: int,
    emailed: int,
    notes: str = "",
) -> None:
    con.execute(
        "INSERT INTO runs (run_at, fetched, new, kept, scored, emailed, notes)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (now_iso(), fetched, new, kept, scored, emailed, notes),
    )
