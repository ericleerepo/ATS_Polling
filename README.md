# job-radar

A daily job-posting radar. Every morning it polls the public ATS boards of
~46 target companies, diffs against everything it has already seen, hard-filters
by role/seniority/location, scores the survivors against my profile with the
Gemini API, and emails a digest: **top 5 LLM-ranked matches above the fold**,
everything else one line each below. Speed is the entire edge — postings show
up in the digest within ~24 hours of publication, while applicant pools are
still thin.

Built for me (new-grad SWE, ML/AI + generalist + forward-deployed roles,
SF/remote-US), but forkable — see [Setup for forkers](#setup-for-forkers).

## Architecture

```
GitHub Actions cron (daily, 06:30 PT)
        │
        ▼
poll ATS boards ──► diff vs SQLite ──► hard filters ──► enrichment
(Greenhouse,        (new postings      (role family,     (keyword score,
 Lever, Ashby)       only)              seniority,        comp extraction,
                                        location)         new-grad flags)
        ┌──────────────────────────────────────────────────────┘
        ▼
LLM scoring (Gemini, batched, strict JSON) ──► digest email (Gmail SMTP)
        │                                            │
        ▼                                            ▼
scores logged to SQLite ◄── feedback.txt ingest ◄── I reply with `147 +` lines
        │
        ▼
workflow commits data/jobs.db back to the repo
(commit history doubles as proof the pipeline runs daily)
```

- **Everything is logged from day one**: every scored posting keeps its four
  subscores, composite, rank, and eventual feedback label in SQLite — the
  eval set assembles itself as a byproduct.
- **Graceful degradation**: if the LLM call fails (or `profile.md` is still
  the placeholder), the digest ranks by deterministic keyword score instead.
- **One broken board never kills the run** — per-company failures land in the
  digest notes and the `runs` table.

## The scoring rubric

Each surviving posting gets four 0–10 subscores from the Gemini API
(`prompts/scoring_prompt.md`, hand-editable): **skill overlap**, **interview
odds** (new-grad-friendliness; clinical-AI domain advantage folds in here as a
hireability multiplier), **growth trajectory**, and **story fit**. The
composite is computed in Python (skill/odds weighted 0.35, growth/story 0.15)
— the LLM never does arithmetic. Each top-5 entry carries a one-line "why" and
a **suggested angle**: which narrative to lead the application with.

## Feedback loop

The digest shows each posting's DB id. I add lines like `147 +` (would apply)
or `152 -` (bad match) to `feedback.txt` and push; the next run ingests them,
updates the DB, clears the file, and injects the ~10 most recent labels into
the scoring prompt as strong/poor-match examples. When `-1` patterns emerge, I
edit the rubric text by hand. At 100+ labels, a learned re-ranker becomes
possible (see Future work).

## Setup for forkers

1. Fork, then edit:
   - `config/companies.yaml` — your target companies. Verify each token
     against the real endpoint first (URLs are in the file header comment).
   - `profile.md` — copy `example_profile.md`, fill it in, delete the
     `<!-- PLACEHOLDER -->` marker on line 1. The file is **gitignored**
     (personal data stays off the public repo); it lives on your machine for
     local runs, and CI rebuilds it from the `PROFILE_MD` secret (below).
     Without it the pipeline runs keyword-rank-only and the digest reminds you.
   - `prompts/scoring_prompt.md` + the `ANGLES` list in
     `src/jobradar/score.py` — your own rubric and narratives.
2. Add GitHub Actions secrets:
   - `GEMINI_API_KEY`
   - `GMAIL_ADDRESS` + `GMAIL_APP_PASSWORD` (Google account → 2FA on →
     App passwords). Optional `DIGEST_TO` if the digest should go elsewhere.
   - `PROFILE_MD` — the full contents of your `profile.md`
     (`gh secret set PROFILE_MD < profile.md`).
3. Run it once by hand: Actions → *daily digest* → *Run workflow*. Green run +
   email in your inbox = done; the cron takes over from there.

Local development:

```sh
uv venv && uv pip install -e ".[dev]"   # or: pip install -e ".[dev]"
python -m pytest
python -m jobradar run --dry-run --no-llm   # live poll, print digest, roll back DB
```

`--dry-run` rolls back all DB writes so a smoke test never consumes postings
the next real run should report as new.

## ATS endpoint notes (quirks discovered)

| Source | Endpoint | Quirks |
|---|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | `content` is HTML-escaped HTML (unescape, then strip tags). `first_published` is the true posting date — `updated_at` moves on any edit. Big boards (Databricks) return multi-MB payloads. |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true` | Cleanest of the three: `descriptionPlain` ready to use, real structured salary under `compensation.compensationTiers[].components`. Skip `isListed: false` rows. |
| Lever | `api.lever.co/v0/postings/{token}?mode=json` | `createdAt` is epoch **milliseconds**. Description split across `descriptionPlain` + `additionalPlain`. Has a `country` code and `workplaceType` — useful for the remote-US filter. |
| Getro (jobs.a16z.com) | `jobs.a16z.com/api-boards/search-jobs` | Backend 500s/times out for non-browser HTTP clients even with browser headers. Poller exists (`pollers/getro.py`) but ships disabled; the board's real value was discovering companies for `companies.yaml`, which happened at build time. |
| ai-jobs.net RSS | — | **Dead.** The domain redirects to aijobs.net and no feed exists anywhere on the site anymore. Dropped as a source. |

Companies with no public structured board (Google Cloud, Hippocratic AI, and
others listed at the bottom of `companies.yaml`) live on the manual checklist
in the digest footer instead — no HTML scraping of custom careers pages, ever.

## Manual boards (in every digest footer)

Wellfound (2×/week), YC Work at a Startup (weekly), HN "Who is Hiring" (first
weekday of the month), Google Cloud careers, Hippocratic AI careers. These are
login-gated, anti-bot, or unstructured — automating them is a non-goal.

## Non-goals

No application auto-fill, no generated cover letters, no automated outreach —
this automates **discovery and triage only**, never contact. No web UI; email
is the interface. No scraping of custom careers pages.

## Future work

- Clickable feedback links in the email (mailto/GitHub-issue tricks) instead
  of hand-editing `feedback.txt`.
- Learned re-ranking: logistic regression on subscores + keyword features
  once 100+ feedback labels accumulate (the training data is already being
  logged).
- More ATS pollers (Workable, Recruitee, Personio) if target companies use them.
- Revisit the Getro/a16z poller if their backend opens up.
