# job-radar — Project Spec

A daily job-posting pipeline: poll ATS boards for ~40 target companies, filter and enrich new postings, score them against my profile with the Claude API, and email a digest with the top 5 LLM-ranked matches above the fold and everything else below.

**Owner:** Eric Lee — new-grad SWE targeting ML/AI engineering, generalist SWE, and forward-deployed/solutions engineering roles in SF/Bay Area or US-remote.

---

## 1. Goals and non-goals

**Goals**
- See relevant postings within ~24 hours of publication (speed is the entire edge).
- One daily email, ruthlessly triaged: top 5 scored matches with one-line rationale, rest listed below.
- Low-friction feedback loop that improves ranking over time.
- Legible public repo: clean README, architecture notes, honest writeup of ATS quirks.

**Non-goals (do not build)**
- No application auto-fill, auto-generated cover letters, or automated outreach/founder messages. Automate discovery and triage only, never contact.
- No web UI or dashboard. Email is the interface.
- No HTML scraping of custom careers pages. Structured endpoints only; custom pages stay on a manual checklist.
- No scraping of Wellfound or workatastartup.com (login-gated, anti-bot, ToS). These are manual checks; the digest footer carries a reminder line.

---

## 2. Architecture

- **Language:** Python
- **Storage:** SQLite, committed to the repo (workflow commits updated DB after each run)
- **Scheduling:** GitHub Actions cron, daily
- **Delivery:** email (SMTP or a transactional email provider — implementer's choice, simplest wins)
- **LLM:** Anthropic API, key in GitHub Actions secret `ANTHROPIC_API_KEY`, never in code
- **Profile:** scoring prompt loads my blurb + condensed resume summary from a profile file; repo ships an `example_profile.md` so others can fork

**Pipeline per run:** poll sources → diff against DB (new postings only) → hard filters → enrichment → LLM scoring (batched) → digest email → ingest `feedback.txt` if present → commit DB.

---

## 3. Sources

**Automated (structured endpoints):**
1. **Greenhouse** public job-board JSON (cleanest; start here)
2. **Lever** public postings JSON
3. **Ashby** public JSON (best structured compensation data)
4. **ai-jobs.net** RSS feed
5. **jobs.a16z.com** (Getro-powered portfolio board; fetch its structured backend). Note: partially overlaps ATS sources — its real value is discovering new companies to add to the token list.

Optionally add Workable/Recruitee/Personio pollers later if target companies use them.

**Manual (digest footer reminder only):** Wellfound (2x/week), YC Work at a Startup (1x/week), HN "Who is Hiring" (first weekday of month).

**Seed board tokens / target companies (~40, grow over time):**
- FDE / applied AI: Sierra, Decagon, Glean, Cresta, Harvey, Cursor (Anysphere), Ramp, Scale AI, Databricks
- Health/clinical AI: Hippocratic AI + adjacent clinical-AI startups (thin applicant pools, domain advantage)
- Labs / large: OpenAI, Anthropic, Google Cloud, Palantir
- Verify each company's actual ATS and record `(company, ats, board_token)` in a config file.

---

## 4. Layer 1 — Hard filters (binary keep/drop, no LLM)

- **Role family — keep if title/description matches any bucket:**
  - ML/AI: `machine learning engineer`, `ML engineer`, `AI engineer`, `applied AI`, `applied scientist`
  - Generalist SWE: `software engineer`, `full stack`, `backend`, `frontend`
  - FDE/solutions: `forward deployed`, `solutions engineer`, `solutions architect`, `deployment strategist`, `technical account`
  - Carve-out: keep hybrid titles like `data scientist` or `ML engineer, analytics` at startups (often 70% engineering; LLM judges). Drop pure data analyst, PM, sales, design, recruiting.
- **Seniority ceiling:** drop titles containing `staff`, `principal`, `director`, `manager`, `lead` (title-level only — "will lead projects" in a description does not drop). Drop descriptions requiring 7+ years. Keep `senior` titles but flag them; the LLM judges whether it's really mid-level.
- **Location:** keep SF/Bay Area, hybrid-SF, remote-US. Drop onsite-elsewhere and non-US remote.
- **Freshness:** only postings new since last run (the diff), with posting date attached.

No clearance/citizenship filtering or flagging — not needed.

---

## 5. Layer 2 — Enrichment (deterministic annotation)

- **Keyword hit score** (feature for the LLM + fallback ranking if the API call fails):
  - High weight: `LLM`, `evals`/`evaluation`, `RAG`, `fine-tuning`, `prompt`, `Claude`, `Anthropic`, `GPT`, `Vertex`, `forward deployed`, `speech-to-text`, `voice`, `streaming`, `clinical`, `health`, `patient`, `medical`
  - Medium weight: `Python`, `TypeScript`, `GCP`/`Google Cloud`, `Terraform`, `PostgreSQL`, `Playwright`, `production`, `full stack`
- **Comp extraction:** Ashby structured salary where present; regex for `$XXX,000`-style ranges elsewhere. Recorded and shown, never filtered on.
- **New-grad signals:** flag `new grad`, `entry level`, `early career`, `0-2 years`, `recent graduate`, university programs. Surface explicitly in the digest.
- **Company metadata:** board source + a priority-list flag (hand-maintained list of ~15 top targets). Priority companies get a visual flag in the digest regardless of score. No stage/category taxonomy.

---

## 6. Layer 3 — LLM scoring

Every posting surviving Layer 1 is scored by the Claude API. **Batch multiple postings per call** to keep cost near zero. Prompt contains: my ~100-word blurb, condensed resume summary, the rubric below, few-shot feedback examples (see §7), and the posting (title, company, location, description, keyword score, flags).

**Rubric — four dimensions, each 0–10:**
1. **Skill overlap:** does the work described match things I've demonstrably done — LLM integration, streaming/real-time systems, ML pipelines, e2e testing, production GCP? Penalize roles whose core stack is absent from my background (heavy C++/systems, mobile-native, pure data engineering).
2. **Interview odds:** would a strong new grad with one intense internship plausibly get an interview? New-grad-friendly scores high; "senior" with 2-3 years scores mid; 5+ years scores low. **Domain advantage folds in here:** health/clinical AI companies raise the score because my clinical-AI internship makes a callback more likely — it's a hireability multiplier, not a preference weight.
3. **Growth trajectory:** shipping across the stack, customer/deployment exposure, proximity to the model layer — versus narrow maintenance work.
4. **Story fit:** could I write a credible two-sentence "why me" leading with either the ProfileHealth streaming migration or the Puma Project? If neither narrative lands, score low.

**Output (strict JSON):** four subscores, weighted composite (skill overlap and interview odds weighted heaviest), a one-line "why this ranked here," and a **suggested angle** — which narrative to lead with (`streaming migration` / `puma project` / `no strong angle`).

**Digest:** top 5 by composite above the fold with why-lines and suggested angles; remainder below sorted by composite, one line each; manual-board reminder in the footer.

---

## 7. Feedback loop

- **Storage:** `feedback` column on postings: `+1` (would apply / applied), `-1` (bad match), null.
- **Capture:** digest shows each posting's ID. I add lines like `147 +` / `152 -` to `feedback.txt` and push; next run ingests, updates DB, clears the file. No endpoints, no UI. (Clickable email links = deferred future work.)
- **Mechanism 1 — few-shot injection (build now):** inject the ~10 most recent labels into the scoring prompt as "strong match" / "poor match" examples (title + one-line summary each).
- **Mechanism 2 — rubric patching (manual, ongoing):** when -1 patterns emerge, I edit the rubric text by hand.
- **Mechanism 3 — learned re-ranking (README future-work only):** logistic regression on subscores + keyword features at 100+ labels. Do not build.
- **Log everything from day one:** every scored posting keeps subscores, composite, and rank in SQLite regardless of feedback — the eval set assembles itself as a byproduct.

---

## 8. Build sequence and budget

1. **Phase 1 (one focused day):** pollers (Greenhouse → Ashby → Lever → RSS), SQLite schema, diff logic, hard filters, enrichment, plain digest email, Actions cron. **LLM layer stubbed** (rank by keyword score). Verify against real endpoints for 2-3 target companies in the first session — real schemas have surprises.
2. **Validate:** run 2-3 days, confirm digest volume and quality are sane.
3. **Phase 2 (one focused day):** LLM scoring, batching, JSON parsing with fallback to keyword rank on failure, feedback ingestion + few-shot injection.
4. **Done = workflow green on schedule + email lands.** Then maintenance mode only. No polish sprints.

---

## 9. Repo hygiene

- Public repo, product-style name (e.g. `job-radar`), standalone (not mixed with other projects).
- README: what it does, architecture sketch, digest screenshot, setup for forkers (`example_profile.md`, config for board tokens), notes on ATS endpoint quirks discovered.
- Secrets in Actions only. DB + feedback file committed (public postings data + my labels — not sensitive; commit history doubles as proof the pipeline runs daily).
- Future-work section: clickable feedback links, learned re-ranking, more ATS pollers.
