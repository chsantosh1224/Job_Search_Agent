# Job Search Agent

Finds remote AI / automation roles at funded startups, ranks them against each user's resume with
an LLM, and prepares research briefs for short, hand-written outreach. Anyone can sign in with
Google, upload a resume and filter jobs by salary (USD) and region.

- Design: [docs/MULTI_USER.md](docs/MULTI_USER.md) (current) · [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) (original)
- Deployment: [DEPLOYMENT.md](DEPLOYMENT.md)

## How it works

1. **Fetch** (shared, daily): YC job board, Hacker News "Who is hiring?", RemoteOK, Remotive and
   startup boards on Greenhouse / Lever / Ashby. Keeps AI, agent, automation and QA / evals
   engineering roles that are remote and open to candidates in India or worldwide.
2. **Rank** (per user, LangGraph): local embeddings shortlist jobs similar to the user's resume
   and at or above their USD minimum; an LLM (OpenRouter free models) assigns a tier, fit score,
   reasons and gaps, and double-checks India eligibility.
3. **Brief** (per user): for the best matches, what the company does, who to contact, which
   project to lead with, talking points and what to verify. Never a drafted message.
4. **Track and digest:** per-user application tracker and a daily email of new matches.

Limits: 20 ranked jobs and 3 briefs per user per day, 800 LLM calls per day overall. Only resume
sections are sent to the model, never name, email or phone.

## Local setup (Windows / PowerShell)

```powershell
docker compose up -d --wait db          # Postgres 16 + pgvector on 127.0.0.1:5434
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\alembic.exe upgrade head
cd ..\frontend; npm install; npm run build; cd ..\backend
.\.venv\Scripts\jobagent.exe serve      # http://127.0.0.1:8000
```

Copy `.env.example` to `.env`. Without Google credentials, set `DEV_LOGIN=true` to sign in by
email from this machine. Emails in `ADMIN_EMAILS` get admin pages (Runs, Evals, Admin).

```powershell
.\.venv\Scripts\jobagent.exe fetch                    # all sources; --source yc to run one
.\.venv\Scripts\jobagent.exe rank                     # rank for every user within limits
.\.venv\Scripts\jobagent.exe rank --email a@b.c --limit 3 --briefs 1   # a small trial
.\.venv\Scripts\jobagent.exe matches --email a@b.c    # a user's ranked jobs
.\.venv\Scripts\jobagent.exe worker                   # daily run + queued runs (Run now, new resumes)
.\.venv\Scripts\jobagent.exe pipeline                 # one full run now: fetch, rank, digests
.\.venv\Scripts\jobagent.exe digest --email a@b.c --preview d.html
.\.venv\Scripts\jobagent.exe refilter                 # re-apply shared filters to stored jobs
```

For frontend development, run `npm run dev` in `frontend/` (port 5173, proxies `/api` to 8000)
alongside `jobagent serve --reload`.

Extra company boards (Greenhouse / Lever / Ashby) can be listed in `backend/config/ats_companies.txt`;
boards linked from other sources' posts are discovered automatically.

### Upgrading from the single-user version

```powershell
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\jobagent.exe bootstrap-admin   # first ADMIN_EMAILS entry takes over existing data
.\.venv\Scripts\jobagent.exe refilter          # the old global salary floor no longer applies
```

## Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest              # uses a separate jobagent_test database
.\.venv\Scripts\python.exe -m pytest -m "not integration"   # no database needed
```

## Evaluation (admin)

Label jobs on the **Evals** page (shown without the AI's scores, so labels stay independent).

```powershell
.\.venv\Scripts\jobagent.exe eval                    # ranking metrics vs labels (no LLM calls)
.\.venv\Scripts\jobagent.exe eval --rank-labeled 10  # first LLM-rank labeled jobs the pipeline skipped
.\.venv\Scripts\jobagent.exe eval --briefs 5         # a second model fact-checks the latest briefs
```

- **Ranking:** precision, recall, F1, precision@5/10, tier accuracy, and AUC of the LLM fit score
  vs. embedding similarity alone (what the LLM adds over vector search).
- **Briefs:** RAGAS-style faithfulness (supported claims / all claims, checked against the exact
  source the brief was written from), specificity and usefulness ratings, plus deterministic
  checks that named people appear in the source and the lead project exists in the resume. The
  judge uses a different model order than the writer to avoid self-grading.

## Status

- [x] Milestones 1–6: ingestion, sources and filters, LangGraph ranking and briefs, dashboard,
  scheduler and digest, evals
- [x] Multi-user: Google sign-in, profiles, per-user ranking with AI limits, salary (USD) and
  region filters, admin page
- [ ] Deploy to Lightsail at jobs.aicruit.in ([DEPLOYMENT.md](DEPLOYMENT.md))
