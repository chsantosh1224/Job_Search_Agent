"""Build the text the LLM sees about the candidate and a job."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Job, Resume, ResumeChunk

PROFILE_SECTIONS = ("summary", "skills", "experience", "projects", "certifications")
MAX_DESCRIPTION_CHARS = 6000


def candidate_profile(resume: Resume) -> str:
    """Resume sections without the header (name, email, phone)."""
    parts = [
        f"{name.upper()}\n{resume.sections[name]}"
        for name in PROFILE_SECTIONS
        if resume.sections.get(name)
    ]
    return "\n\n".join(parts)[:8000]


def matching_chunks(session: Session, resume_id: int, embedding: list[float], k: int = 3) -> str:
    """The k resume projects/bullets most similar to a job: what the candidate should lead with."""
    chunks = session.scalars(
        select(ResumeChunk)
        .where(ResumeChunk.resume_id == resume_id,
               ResumeChunk.section.in_(("experience", "projects")))
        .order_by(ResumeChunk.embedding.cosine_distance(embedding))
        .limit(k)
    )
    return "\n".join(f"- {chunk.content}" for chunk in chunks)


def salary_text(job: Job) -> str:
    if job.salary_max_inr:
        rate = get_settings().usd_to_inr
        low = (job.salary_min_inr or job.salary_max_inr) / rate / 1000
        usd = f"${low:.0f}k-${job.salary_max_inr / rate / 1000:.0f}k per year"
        return f"{job.salary_raw} (≈ {usd})" if job.salary_raw else usd
    return "Not stated"


_EXTRA_LABELS = {
    "one_liner": "One-liner",
    "team_size": "Team size",
    "visa": "Visa",
    "min_experience": "Minimum experience",
    "equity": "Equity",
    "hiring_manager": "Hiring manager",
    "job_type": "Job type",
    "commitment": "Commitment",
    "employment_type": "Employment type",
}


def extra_text(job: Job) -> str:
    extra = job.extra or {}
    lines = [f"{label}: {extra[key]}" for key, label in _EXTRA_LABELS.items() if extra.get(key)]
    if job.company and job.company.yc_batch:
        lines.append(f"YC batch: {job.company.yc_batch}")
    founders = [
        f"{f['name']} ({f['title']})" if f.get("title") else f["name"]
        for f in extra.get("founders") or []
    ]
    if founders:
        lines.append("Founders: " + ", ".join(founders))
    return "\n".join(lines)


def job_embedding_text(job: Job) -> str:
    company = job.company.name if job.company else ""
    return f"{job.title}\n{company}\n{job.description[:3000]}"
