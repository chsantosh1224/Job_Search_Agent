# Job Search Agent — Requirements & Architecture

**Status:** Approved 2026-10-27 · Single-user version; superseded in part by [MULTI_USER.md](MULTI_USER.md)

## 1. Goal

A personal agent that finds **remote roles at funded startups**, ranks them against the candidate's resume, and prepares a **research brief** per job so the candidate can write their own outreach. It also doubles as a **portfolio project** showing LangGraph, RAG and LLM evaluation.

**Positioning:** "Senior automation engineer who builds production AI agents" (not a beginner).

## 2. Target profile

| Item | Value |
|---|---|
| Roles | AI Engineer, Agent Automation Engineer, Automation Engineer, AI QA / Evals Engineer |
| Seniority | Mid to Staff (flexible on title) |
| Location | Remote, India-based or global (incl. contractor) |
| Time zones | Night and early-morning overlap OK (US / EU) |
| Companies | Any funded startup |
| Min. compensation | Candidate's own floor (kept in settings, not in the repo). Missing salary shows as **"Unknown"**, not hidden |

**Ranking tiers**
- **Tier 1:** Agent / Automation Engineer and AI QA / Evals roles at AI startups
- **Tier 2:** AI / LLM Engineer roles mentioning agents, document AI, RAG or workflow automation
- **Tier 3:** Senior Automation / SDET roles at AI-first startups

## 3. Features (in scope)

1. **Find jobs** from approved sources (§5), deduplicated.
2. **Filter:** remote and eligible from India, salary at or above the candidate's floor, or unknown, role family match.
3. **Rank:** tier, fit score 0–100, short "why it fits / gaps" against the resume.
4. **Research brief** (top jobs only): what the company does, funding/stage, founder or hiring manager if public, which of the candidate's projects to lead with, 2–3 talking points. **No drafted messages.**
5. **Application tracker:** New → Shortlisted → Applied → Interviewing → Offer / Rejected, with notes.
6. **Dashboard** at `jobs.aicruit.in` behind a **single-user login**.
7. **Daily email digest** (Resend) plus an on-demand **"Run now"** button.
8. **Evals:** labeled set of ~30 jobs to score ranking quality, plus LLM-as-judge (and RAGAS faithfulness) on briefs to catch hallucinated company facts.

**Out of scope:** auto-applying, sending messages to anyone, scraping LinkedIn / Naukri / Wellfound (their terms forbid it; the dashboard may show search links the candidate opens themselves).

## 4. Architecture

```
          ┌──────────── daily cron (≈05:00 IST) / "Run now" ───────────┐
          ▼                                                            │
  LangGraph pipeline                                                   │
  fetch → normalize/dedupe → hard filters → embed + similarity          │
  prefilter → LLM rank (top ~40) → research brief (top ~10) → store    │
          │                                                            │
          ▼                                                            │
  PostgreSQL 16 + pgvector ◄── FastAPI (auth, jobs, tracker, evals) ◄──┤
                                     ▲                                 │
                          React dashboard (Vite + TS)                  │
                                                                       │
  Resend daily digest ◄────────────────────────────────────────────────┘
```

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy, Alembic |
| Agent | LangGraph |
| LLM | OpenRouter free models with automatic fallback list (≈1,000 req/day with the $10 credit; pipeline budgets ~50–100/day) |
| Embeddings | fastembed (ONNX, `bge-small-en`), local, no API cost |
| DB | PostgreSQL 16 + pgvector in Docker |
| Frontend | React + Vite + TypeScript + Tailwind |
| Auth | Single user, hashed password in env, HTTP-only JWT cookie |
| Email | Resend, domain verified via GoDaddy DNS |
| Hosting | Existing AWS Lightsail instance (2 GB, shared with invoice agent), Docker Compose, HTTPS reverse proxy, 2 GB swap |
| Observability | Structured logs, run history table, optional LangSmith traces |

## 5. Job sources

| Source | Access method |
|---|---|
| YC job board (ycombinator.com/jobs) | Public pages; verify access & terms at build time |
| Hacker News "Who's Hiring" | Official HN / Algolia API |
| RemoteOK | Public API (attribution required) |
| Remotive | Public API |
| Greenhouse / Lever / Ashby | Public job-board APIs per company; company list seeded from YC directory and HN posts |

## 6. Milestones

1. Project skeleton, DB schema, resume ingestion
2. Source connectors + dedupe + hard filters
3. LangGraph ranking + research briefs
4. FastAPI + React dashboard + login + tracker
5. Scheduler + Resend digest
6. Eval set + evaluation page
7. Deploy to Lightsail at `jobs.aicruit.in`, README for GitHub

## 7. Open items to confirm during build

- What reverse proxy the invoice agent already uses on ports 80/443 (nginx / Caddy), so both sites can share it.
- Public GitHub repo for this project (recommended for portfolio).
- Digest send time (default 07:00 IST) and number of jobs per digest (default top 10).
