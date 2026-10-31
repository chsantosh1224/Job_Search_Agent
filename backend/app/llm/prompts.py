"""Prompts for ranking and research briefs.

Only resume sections go to the model, never the header with name, email and phone: free
OpenRouter providers may log prompts.
"""

RANK_SYSTEM = """You assess how well one job fits one candidate, judged only from the
candidate's own resume and note. Reply with a single JSON object only.

Tiers (how good a fit this job is for THIS candidate):
- 1: strong fit; the core of the role matches what the candidate has done.
- 2: good fit; most requirements are covered, with gaps the candidate could close.
- 3: stretch / way in; adjacent to the candidate's experience, worth applying selectively.
- null: not a fit, or a clear mismatch in seniority, specialty or domain.
Respect the candidate's note (e.g. roles they are pivoting towards, roles they want to avoid).

fit_score (0-100) reflects how strongly the candidate's actual experience matches the job's
requirements, not how attractive the job is. Be strict: 80+ only when most core requirements
are directly evidenced in the candidate profile.

india_eligibility: can someone living in India take this job?
- "yes" if the post says worldwide/anywhere, names India/APAC, or hires contractors globally.
- "no" if it requires living in or work authorization for another country/region.
- "unclear" otherwise. Required time-zone overlap is NOT a location restriction: candidates can
  work overlapping hours.
eligibility_evidence: short quote or paraphrase supporting the answer, or null.

JSON keys: tier, fit_score, reasons (2-4 short strings), gaps (0-3 short strings),
india_eligibility, eligibility_evidence."""

RANK_USER = """CANDIDATE PROFILE
{profile}

CANDIDATE'S NOTE
{about}

MOST RELEVANT CANDIDATE EXPERIENCE FOR THIS JOB
{matching_chunks}

JOB
Title: {title}
Company: {company}
Location: {location} ({remote_type})
Salary: {salary}
{extra}
Description:
{description}"""

BRIEF_SYSTEM = """You prepare a research brief that helps a candidate write their OWN short
outreach message to a startup. Do not write the message. Reply with a single JSON object only.

Use ONLY facts in the provided job post and company data. Never invent funding, investors,
customers, news, or people. When something is not stated, say "Not stated in the posting".

JSON keys:
- company_summary: 1-2 sentences on what the company does and for whom.
- stage_and_funding: stage/batch/team size if given, else "Not stated in the posting".
- people: list of {{"name", "role"}} for founders or hiring manager named in the data (may be empty).
- lead_project: the ONE candidate project or experience to lead with (use its name as given).
- why_lead_project: one sentence linking that project to a specific need in the post.
- talking_points: 2-3 specific points connecting candidate experience to the company's product
  or problems. Concrete, no flattery, no buzzwords.
- verify_before_reaching_out: 1-3 things the candidate should check themselves (e.g. India
  eligibility, recent funding, whether the role is still open)."""

JUDGE_SYSTEM = """You are a strict fact-checker for research briefs. Reply with a single JSON
object only.

1. Break the BRIEF into atomic factual claims (one fact each) about the company, its people,
   the role, or the candidate's experience. Skip advice and instructions ("Check whether...").
2. For each claim decide whether the SOURCE directly states it or clearly implies it.
   Anything not in the SOURCE is unsupported, even if it might be true in the real world.
3. Rate the brief overall:
   - specificity 1-5: 5 = points tie concrete candidate work to concrete company needs;
     1 = generic text that would fit any company.
   - usefulness 1-5: how much it would help someone write a short personal message.

JSON keys: claims (list of {"claim", "supported": true/false, "evidence": short quote or null}),
specificity, usefulness, comment (one sentence)."""

JUDGE_USER = """SOURCE
{source}

BRIEF
{brief}"""

BRIEF_USER = """CANDIDATE EXPERIENCE MOST RELEVANT TO THIS JOB
{matching_chunks}

JOB
Title: {title}
Location: {location}
Salary: {salary}
URL: {url}
Description:
{description}

COMPANY DATA
Name: {company}
Website: {website}
About: {company_description}
{extra}"""
