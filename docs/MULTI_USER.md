# Multi-user design

Status: approved 2026-10-27. Supersedes the single-user parts of REQUIREMENTS.md.

## Decisions

| Topic | Decision |
|---|---|
| Who | Anyone can sign up (open sign-up). Every visitor must sign in. |
| Sign-in | Google sign-in only (OpenID Connect). No passwords. |
| Admin | Emails in `ADMIN_EMAILS`. The first admin keeps the existing single-user data. |
| Profile | Name, resume PDF, minimum salary in **USD**, optional "about me" note for the AI, consent. |
| Job scope | Shared AI / agent / automation / QA-evals engineering jobs board (role families stay a setting). |
| Locations | Remote only: Worldwide remote, India remote, Remote (region not stated). |
| Jobs page filters | USD salary range, "Include unknown salary" checkbox, location checkboxes, text, tier. |
| AI ranking | Per user, against that user's resume. Only jobs at or above the user's USD minimum (or unknown salary). |
| AI limits | Per user per day: 20 ranked jobs, 3 briefs. Overall: 800 LLM calls per day. All settings. |
| Briefs, tracker, digest | Per user. Digest goes to the user's Google email (needs Resend). |
| Evals, runs, Run now | Admin only. |

## What changes

- **Fetching is shared** and no longer applies a salary floor: salary is per user. Hard filters
  keep only role family, remote/region, freshness and duplicates.
- **Ranking runs per user** after each daily fetch, and right after a user uploads a resume (a
  queued per-user run, so new users see matches within minutes).
- **AI usage** is recorded per user per day; a run stops when the user's or the global limit is
  reached, and the rest carries over to the next day.
- **The ranking prompt** no longer contains one person's positioning; it uses the user's resume
  and optional "about me" note. Tiers become strong / good / stretch fit.
- **Privacy:** sign-up shows that resume text is sent to AI model providers (free models may log
  prompts); name, email and phone are still never sent. Users can delete their account and data.

## Not in this change

- Per-user target roles (fetching other role families).
- Locations other than India / worldwide remote.
- Users bringing their own OpenRouter key.
