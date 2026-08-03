"""Digest rendering: top 5 above the fold, everything else one line each."""

from dataclasses import dataclass

from .model import Annotations, Posting, Score

TOP_N = 5

MANUAL_FOOTER = [
    "Wellfound — check 2x/week (login-gated, no API)",
    "YC Work at a Startup — check 1x/week",
    'HN "Who is Hiring" — first weekday of the month',
    "Google Cloud careers + Hippocratic AI careers — custom pages, no public ATS feed",
]

FEEDBACK_HOWTO = (
    "Feedback: add lines like `147 +` (would apply) or `152 -` (bad match) "
    "to feedback.txt and push. Next run ingests them into the ranking prompt."
)


@dataclass
class Entry:
    id: int
    posting: Posting
    ann: Annotations
    score: Score | None

    @property
    def sort_key(self) -> tuple[float, float]:
        composite = self.score.composite if self.score else -1.0
        return (composite, self.ann.keyword_score)


def ranked(entries: list[Entry]) -> list[Entry]:
    return sorted(entries, key=lambda e: e.sort_key, reverse=True)


def _badges(e: Entry) -> list[str]:
    out = []
    if e.ann.priority_company:
        out.append("★ priority")
    if e.ann.new_grad_flag:
        out.append("new-grad signal")
    if e.ann.senior_flag:
        out.append("senior-titled")
    if e.ann.hybrid_flag:
        out.append("hybrid role")
    return out


def _comp(p: Posting) -> str:
    if p.comp_min and p.comp_max:
        return f"${p.comp_min / 1000:.0f}K–${p.comp_max / 1000:.0f}K"
    return ""


def _score_line(e: Entry) -> str:
    if e.score:
        s = e.score
        return (
            f"score {s.composite:.1f} (skill {s.skill:.0f} · odds {s.odds:.0f} · "
            f"growth {s.growth:.0f} · story {s.story:.0f})"
        )
    return f"keyword score {e.ann.keyword_score:.0f} (LLM scoring unavailable)"


def subject(entries: list[Entry], date: str) -> str:
    if not entries:
        return f"job-radar {date}: no new matches"
    top = ranked(entries)[0]
    return (
        f"job-radar {date}: {len(entries)} new · "
        f"top: {top.posting.company} — {top.posting.title}"
    )


def render_text(entries: list[Entry], date: str, notes: list[str] | None = None) -> str:
    entries = ranked(entries)
    lines = [f"job-radar digest — {date}", ""]
    for note in notes or []:
        lines += [f"NOTE: {note}", ""]

    if not entries:
        lines.append("No new matching postings since the last run.")
    else:
        lines.append(f"=== TOP {min(TOP_N, len(entries))} ===")
        for e in entries[:TOP_N]:
            p = e.posting
            badge = f"  [{', '.join(_badges(e))}]" if _badges(e) else ""
            lines += [
                "",
                f"[{e.id}] {p.title} — {p.company}",
                f"     {p.location}" + (f" · {_comp(p)}" if _comp(p) else "") + badge,
                f"     {_score_line(e)}",
            ]
            if e.score:
                lines.append(f"     why: {e.score.why}")
                lines.append(f"     angle: {e.score.angle}")
            lines.append(f"     {p.url}")
        rest = entries[TOP_N:]
        if rest:
            lines += ["", f"=== ALSO NEW ({len(rest)}) ==="]
            for e in rest:
                p = e.posting
                comp = f" · {_comp(p)}" if _comp(p) else ""
                star = "★ " if e.ann.priority_company else ""
                score = f"{e.score.composite:.1f}" if e.score else f"kw {e.ann.keyword_score:.0f}"
                lines.append(f"[{e.id}] {score} {star}{p.title} — {p.company} ({p.location}){comp} {p.url}")

    lines += ["", "--- manual boards ---"]
    lines += [f"- {m}" for m in MANUAL_FOOTER]
    lines += ["", FEEDBACK_HOWTO]
    return "\n".join(lines)


def render_html(entries: list[Entry], date: str, notes: list[str] | None = None) -> str:
    entries = ranked(entries)
    h = [
        '<div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:680px;'
        'margin:0 auto;color:#1a1a1a">',
        f'<h2 style="margin:16px 0 4px">job-radar — {date}</h2>',
    ]
    for note in notes or []:
        h.append(
            f'<p style="background:#fff3cd;padding:8px 12px;border-radius:6px">{note}</p>'
        )

    if not entries:
        h.append("<p>No new matching postings since the last run.</p>")
    else:
        h.append(f'<h3 style="margin:20px 0 8px">Top {min(TOP_N, len(entries))}</h3>')
        for e in entries[:TOP_N]:
            p = e.posting
            badges = "".join(
                f'<span style="background:#eef2ff;border-radius:4px;padding:1px 6px;'
                f'margin-left:6px;font-size:12px">{b}</span>'
                for b in _badges(e)
            )
            comp = f" · {_comp(p)}" if _comp(p) else ""
            h.append(
                '<div style="border:1px solid #e5e5e5;border-radius:8px;padding:12px;'
                'margin:0 0 10px">'
                f'<div><a href="{p.url}" style="font-weight:600;text-decoration:none">'
                f"{p.title}</a> — {p.company}{badges}</div>"
                f'<div style="color:#555;font-size:13px">{p.location}{comp}</div>'
                f'<div style="color:#555;font-size:13px">{_score_line(e)}</div>'
                + (
                    f'<div style="font-size:13px;margin-top:4px">{e.score.why}<br>'
                    f"<b>angle:</b> {e.score.angle}</div>"
                    if e.score
                    else ""
                )
                + f'<div style="color:#999;font-size:12px;margin-top:4px">id {e.id}</div>'
                "</div>"
            )
        rest = entries[TOP_N:]
        if rest:
            h.append(f'<h3 style="margin:20px 0 8px">Also new ({len(rest)})</h3>')
            h.append('<ul style="padding-left:18px;font-size:13px;line-height:1.7">')
            for e in rest:
                p = e.posting
                star = "★ " if e.ann.priority_company else ""
                score = f"{e.score.composite:.1f}" if e.score else f"kw {e.ann.keyword_score:.0f}"
                comp = f" · {_comp(p)}" if _comp(p) else ""
                h.append(
                    f'<li>[{e.id}] <b>{score}</b> {star}<a href="{p.url}">{p.title}</a>'
                    f" — {p.company} <span style='color:#777'>({p.location}{comp})</span></li>"
                )
            h.append("</ul>")

    h.append('<hr style="border:none;border-top:1px solid #e5e5e5;margin:20px 0">')
    h.append('<p style="font-size:12px;color:#777"><b>Manual boards:</b><br>')
    h.append("<br>".join(MANUAL_FOOTER) + "</p>")
    h.append(f'<p style="font-size:12px;color:#777">{FEEDBACK_HOWTO}</p>')
    h.append("</div>")
    return "\n".join(h)
