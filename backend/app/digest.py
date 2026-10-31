"""Daily email digest of new matches, sent with Resend.

A match is included once: after a successful send its notified_at is set. Job text comes from
outside sources, so everything is HTML-escaped. Nothing is sent when there is nothing new.
"""

import html
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import Job, JobMatch, ResearchBrief, User
from app.resume.ingest import get_active_resume

log = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
TIER_COLORS = {1: "#047857", 2: "#0369a1", 3: "#b45309"}


@dataclass
class DigestItem:
    match: JobMatch
    job: Job
    brief: ResearchBrief | None

    @property
    def salary(self) -> str:
        job = self.job
        if not job.salary_max_inr:
            return "Salary unknown"
        rate = get_settings().usd_to_inr
        low = round(job.salary_min_inr / rate / 1000) if job.salary_min_inr else None
        high = round(job.salary_max_inr / rate / 1000)
        return f"${high}k" if low in (None, high) else f"${low}k–${high}k"


def collect(session: Session, user: User, limit: int) -> tuple[list[DigestItem], int]:
    """The user's new (not yet emailed) tiered matches, best first, plus the total count."""
    resume = get_active_resume(session, user.id)
    if resume is None:
        return [], 0
    where = (JobMatch.resume_id == resume.id, JobMatch.tier.is_not(None),
             JobMatch.notified_at.is_(None), Job.passed_filters.is_(True))
    total = session.scalar(
        select(func.count()).select_from(JobMatch).join(Job, Job.id == JobMatch.job_id)
        .where(*where)
    )
    rows = session.execute(
        select(JobMatch, Job, ResearchBrief)
        .join(Job, Job.id == JobMatch.job_id)
        .outerjoin(ResearchBrief, and_(ResearchBrief.job_id == Job.id,
                                       ResearchBrief.resume_id == resume.id))
        .where(*where)
        .order_by(JobMatch.tier, JobMatch.fit_score.desc())
        .limit(limit)
    ).all()
    return [DigestItem(m, j, b) for m, j, b in rows], total


def subject(items: list[DigestItem], total: int) -> str:
    best = min(item.match.tier for item in items)
    return f"{total} new job match{'es' if total != 1 else ''} (best: Tier {best})"


def render_text(items: list[DigestItem], total: int, dashboard_url: str) -> str:
    lines = [f"{total} new matches. Top {len(items)}:", ""]
    for item in items:
        job, match = item.job, item.match
        company = job.company.name if job.company else "Unknown"
        lines.append(f"Tier {match.tier} · {match.fit_score}/100 · {job.title} — {company}")
        lines.append(f"  {item.salary} · {dashboard_url}/jobs/{job.id}")
        if item.brief and item.brief.content.get("lead_project"):
            lines.append(f"  Lead with: {item.brief.content['lead_project']}")
        lines.append("")
    lines.append(f"All matches: {dashboard_url}/jobs")
    return "\n".join(lines)


def render_html(items: list[DigestItem], total: int, dashboard_url: str) -> str:
    esc = html.escape
    cards = []
    for item in items:
        job, match = item.job, item.match
        company = esc(job.company.name if job.company else "Unknown")
        color = TIER_COLORS.get(match.tier, "#57534e")
        reason = esc(match.reasons[0]) if match.reasons else ""
        lead = item.brief.content.get("lead_project") if item.brief else None
        lead_html = (f'<div style="margin-top:6px;font-size:13px;color:#6d28d9">'
                     f"Lead with: <b>{esc(lead)}</b></div>") if lead else ""
        cards.append(f"""
<tr><td style="padding:14px 0;border-bottom:1px solid #e7e5e4">
  <div style="font-size:12px;font-weight:600;color:{color}">Tier {match.tier} · {match.fit_score}/100</div>
  <a href="{esc(dashboard_url)}/jobs/{job.id}" style="font-size:16px;font-weight:600;color:#1c1917;text-decoration:none">{esc(job.title)}</a>
  <div style="font-size:13px;color:#57534e">{company} · {esc(item.salary)}</div>
  <div style="margin-top:6px;font-size:13px;color:#44403c">{reason}</div>
  {lead_html}
</td></tr>""")
    more = (f'<p style="font-size:13px;color:#57534e">and {total - len(items)} more on the '
            f"dashboard.</p>") if total > len(items) else ""
    return f"""<!doctype html>
<html><body style="margin:0;background:#fafaf9;font-family:-apple-system,Segoe UI,Roboto,sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="100%" style="max-width:560px;background:#ffffff;border:1px solid #e7e5e4;border-radius:8px" cellpadding="0" cellspacing="0">
<tr><td style="padding:20px 24px">
  <div style="font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:#78716c">Job Search Agent</div>
  <h1 style="margin:6px 0 4px;font-size:20px;color:#1c1917">{total} new match{"es" if total != 1 else ""}</h1>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{"".join(cards)}</table>
  {more}
  <p style="margin-top:18px"><a href="{esc(dashboard_url)}/jobs" style="background:#1c1917;color:#ffffff;padding:8px 14px;border-radius:6px;font-size:14px;text-decoration:none">Open dashboard</a></p>
</td></tr></table>
<p style="font-size:11px;color:#a8a29e">Sent by your job search agent. Briefs use only the job posting; verify before reaching out.</p>
</td></tr></table>
</body></html>"""


Sender = Callable[[Settings, str, str, str, str], None]  # settings, to, subject, html, text


def send_with_resend(settings: Settings, to: str, subject_line: str, html_body: str,
                     text: str) -> None:
    response = httpx.post(
        RESEND_URL,
        headers={"Authorization": f"Bearer {settings.resend_api_key}"},
        json={"from": settings.digest_from, "to": [to],
              "subject": subject_line, "html": html_body, "text": text},
        timeout=30,
    )
    response.raise_for_status()


def send_digest(session: Session, user: User, sender: Sender = send_with_resend,
                settings: Settings | None = None) -> dict:
    """Email the user's new matches and mark them notified. Returns stats for the run record."""
    settings = settings or get_settings()
    if not settings.resend_api_key:
        return {"sent": False, "reason": "not configured (RESEND_API_KEY)"}
    items, total = collect(session, user, settings.digest_max_jobs)
    if not items:
        return {"sent": False, "reason": "no new matches"}
    dashboard = settings.public_url.rstrip("/")
    try:
        sender(settings, user.email, subject(items, total),
               render_html(items, total, dashboard), render_text(items, total, dashboard))
    except httpx.HTTPError as exc:
        log.warning("Digest send to user %s failed: %s", user.id, exc)
        return {"sent": False, "reason": f"send failed: {exc}"[:300]}
    now = datetime.now(UTC)
    for item in items:
        item.match.notified_at = now
    return {"sent": True, "jobs": len(items), "new_matches": total}


def send_digests(session: Session, sender: Sender = send_with_resend,
                 settings: Settings | None = None) -> dict:
    """One digest per active user; stats keyed by user id (no emails in run records)."""
    users = session.scalars(select(User).where(User.is_active.is_(True)).order_by(User.id))
    results = {f"user {u.id}": send_digest(session, u, sender, settings) for u in users}
    return {"sent": sum(r["sent"] for r in results.values()), "per_user": results}
