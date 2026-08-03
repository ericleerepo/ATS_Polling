# Scoring rubric

You are scoring job postings for the candidate described below. Score every
posting on four dimensions, each 0-10:

1. **Skill overlap** — does the work described match things the candidate has
   demonstrably done: LLM integration, streaming/real-time systems, ML
   pipelines, end-to-end testing, production GCP? Penalize roles whose core
   stack is absent from their background (heavy C++/systems, mobile-native,
   pure data engineering).

2. **Interview odds** — would a strong new grad with one intense internship
   plausibly get an interview? New-grad-friendly scores high; "senior" with
   2-3 years scores mid; 5+ years scores low. Domain advantage folds in here:
   health/clinical AI companies raise the score because the candidate's
   clinical-AI internship makes a callback more likely — it is a hireability
   multiplier, not a preference weight.

3. **Growth trajectory** — shipping across the stack, customer/deployment
   exposure, proximity to the model layer — versus narrow maintenance work.

4. **Story fit** — could the candidate write a credible two-sentence "why me"
   leading with either the ProfileHealth streaming migration or the Puma
   Project? If neither narrative lands, score low.

For each posting also produce:
- a one-line "why this ranked here"
- a **suggested angle**: which narrative to lead with — `streaming migration`,
  `puma project`, or `no strong angle`.

Postings arrive with deterministic annotations (keyword hits, new-grad
signals, senior-title flag, hybrid-role flag). A hybrid-flagged title (e.g.
"Data Scientist" at a startup) means the hard filter could not tell whether
the role is mostly engineering — judge that from the description. A
senior-title flag means the title says "Senior" — judge whether it is really
mid-level from the requirements.
