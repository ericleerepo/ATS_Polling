"""Pipeline orchestrator.

    python -m jobradar run [--dry-run] [--no-llm]

Per run: poll -> diff -> filter -> enrich -> LLM score -> digest email ->
ingest feedback -> record run. --dry-run prints the digest instead of
emailing and rolls back all DB writes, so a smoke test never eats postings
the next real run should treat as new.
"""

import argparse
import sys
from datetime import datetime, timezone

from . import config, db, digest, emailer, enrich, feedback, filters, score
from .config import Settings, load_companies, load_profile
from .pollers import POLLERS


def run(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    companies = load_companies()
    con = db.connect(config.DB_PATH)
    notes: list[str] = []

    # --- poll + diff + filter + enrich ---
    seen = db.seen_keys(con)
    fetched = new = kept = 0
    entries: list[digest.Entry] = []
    for company in companies:
        try:
            postings = POLLERS[company.ats](company)
        except Exception as e:  # noqa: BLE001 — one broken board never kills the run
            notes.append(f"poller {company.name}: {type(e).__name__}: {e}")
            continue
        fetched += len(postings)
        for p in postings:
            if p.key in seen:
                continue
            seen.add(p.key)
            new += 1
            fr = filters.apply(p)
            ann = enrich.annotate(p, company, fr)
            pid = db.insert_posting(con, p, ann)
            if ann.kept:
                kept += 1
                entries.append(digest.Entry(id=pid, posting=p, ann=ann, score=None))
    print(f"fetched {fetched} postings, {new} new, {kept} kept", flush=True)

    # --- LLM scoring (falls back to keyword rank on any failure) ---
    scored = 0
    profile = load_profile()
    if entries and not args.no_llm:
        if profile is None:
            notes.append(
                "profile.md is still the placeholder — LLM scoring skipped, "
                "ranked by keyword score. Fill in profile.md to enable it."
            )
        elif not settings.gemini_api_key:
            notes.append("GEMINI_API_KEY not set — ranked by keyword score.")
        else:
            rubric = config.PROMPT_PATH.read_text()
            few_shot = feedback.few_shot_examples(con)
            rendered = [score.render_posting(e.id, e.posting, e.ann) for e in entries]
            scores, errors = score.score_all(settings, rubric, profile, few_shot, rendered)
            notes.extend(f"scoring: {err}" for err in errors)
            for e in entries:
                if s := scores.get(e.id):
                    e.score = s
                    db.record_score(con, e.id, s)
                    scored += 1
                else:
                    db.record_score_error(con, e.id, "no score returned")
    print(f"scored {scored}/{len(entries)}", flush=True)
    for n in notes:  # digest notes also go to the run log — the email may never arrive
        print(f"NOTE: {n}", flush=True)

    # --- digest ---
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ranked = digest.ranked(entries)
    db.mark_digest(con, [e.id for e in ranked], date)
    subject = digest.subject(entries, date)
    text = digest.render_text(entries, date, notes=notes)
    html = digest.render_html(entries, date, notes=notes)
    emailed = 0
    if args.dry_run or args.no_email:
        print(f"\n=== {subject} ===\n{text}")
    else:
        emailer.send(settings, subject, text, html)
        emailed = 1
        print(f"emailed digest to {settings.digest_to}", flush=True)

    # --- feedback ingest (labels apply to the next run's few-shot examples) ---
    if not args.dry_run:
        applied, bad = feedback.ingest(con, config.FEEDBACK_PATH)
        if applied:
            print(f"ingested {applied} feedback label(s)")
        for line in bad:
            print(f"feedback: could not apply {line!r}", file=sys.stderr)

    db.record_run(
        con,
        fetched=fetched,
        new=new,
        kept=kept,
        scored=scored,
        emailed=emailed,
        notes="; ".join(notes),
    )
    if args.dry_run:
        print("\n(dry run: all DB changes rolled back)")
    else:
        con.commit()
    con.close()
    return 0


def backfill(args: argparse.Namespace) -> int:
    """Score kept postings that never got an LLM score (e.g. rate-limited).

    Digest ranks already sent are left alone — this fills in the scores so the
    eval set and future few-shot examples are complete.
    """
    settings = Settings.from_env()
    profile = load_profile()
    if profile is None:
        print("profile.md is missing or still the placeholder", file=sys.stderr)
        return 1
    if not settings.gemini_api_key:
        print("GEMINI_API_KEY not set", file=sys.stderr)
        return 1

    con = db.connect(config.DB_PATH)
    rows = db.unscored_kept(con, limit=args.limit)
    if not rows:
        print("nothing to backfill")
        return 0

    batches = (len(rows) + score.BATCH_SIZE - 1) // score.BATCH_SIZE
    print(f"backfilling {len(rows)} postings in ~{batches} batches", flush=True)
    rendered = [
        score.render_posting(r["id"], db.posting_from_row(r), db.annotations_from_row(r))
        for r in rows
    ]

    def persist(batch_scores):
        """Commit each batch as it lands so a timeout can't discard the work."""
        for posting_id, s in batch_scores.items():
            db.record_score(con, posting_id, s)
        con.commit()

    scores, errors = score.score_all(
        settings,
        config.PROMPT_PATH.read_text(),
        profile,
        feedback.few_shot_examples(con),
        rendered,
        progress=lambda done, total, n: print(
            f"  batch {done}/{total} — {n} scored (saved)", flush=True
        ),
        on_scored=persist,
    )
    for r in rows:
        if r["id"] not in scores:
            db.record_score_error(con, r["id"], "backfill: no score returned")
    con.commit()
    con.close()
    for e in errors:
        print(f"NOTE: {e}", flush=True)
    print(f"scored {len(scores)}/{len(rows)}")
    return 0 if scores else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="jobradar")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="execute one full pipeline run")
    run_p.add_argument("--dry-run", action="store_true", help="print digest, roll back DB")
    run_p.add_argument("--no-email", action="store_true", help="print digest instead of sending")
    run_p.add_argument("--no-llm", action="store_true", help="skip LLM scoring (keyword rank)")
    fill_p = sub.add_parser("backfill", help="score kept postings that have no LLM score")
    fill_p.add_argument("--limit", type=int, help="only backfill the first N postings")
    args = parser.parse_args()
    return backfill(args) if args.command == "backfill" else run(args)


if __name__ == "__main__":
    sys.exit(main())
