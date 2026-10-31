"""Persist RawJobs: upsert companies and jobs, classify location, dedupe, apply filters."""

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.filters import LLM_INDIA_PREFIX, filter_reason, is_target_role
from app.models import Company, Job
from app.normalize.location import classify_location
from app.normalize.text import normalize_name
from app.sources.base import RawJob


@dataclass
class StoreStats:
    fetched: int = 0
    off_target: int = 0  # not stored: title outside the target role families
    new: int = 0
    updated: int = 0
    passed: int = 0
    errors: int = 0

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def dedupe_key(company: str, title: str) -> str:
    # Titles keep every word ("AI Engineer" must not collapse into "Engineer").
    title_key = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return hashlib.sha256(f"{normalize_name(company)}|{title_key}".encode()).hexdigest()


def get_or_create_company(session: Session, raw: RawJob) -> Company | None:
    name = raw.company_name.strip()
    normalized = normalize_name(name)
    if not normalized:
        return None
    company = session.scalar(select(Company).where(Company.normalized_name == normalized))
    if company is None:
        company = Company(name=name[:255], normalized_name=normalized[:255])
        session.add(company)
    company.website = company.website or raw.company_website
    company.description = company.description or raw.company_description
    company.yc_batch = company.yc_batch or raw.yc_batch
    if raw.ats_links and not company.ats_type:
        company.ats_type, company.ats_slug = min(raw.ats_links)
    session.flush()
    return company


def store_job(session: Session, raw: RawJob, stats: StoreStats) -> Job | None:
    stats.fetched += 1
    company = get_or_create_company(session, raw)  # also records discovered ATS boards
    if not is_target_role(raw.title):
        stats.off_target += 1
        return None

    job = session.scalar(
        select(Job).where(Job.source == raw.source, Job.source_job_id == raw.source_job_id)
    )
    if job is None:
        job = Job(source=raw.source, source_job_id=raw.source_job_id, extra={})
        session.add(job)
        stats.new += 1
    else:
        stats.updated += 1

    job.url = raw.url[:1000]
    job.title = raw.title[:500]
    job.company = company
    job.last_seen_at = datetime.now(UTC)
    job.dedupe_key = dedupe_key(raw.company_name, raw.title)
    # Sources sometimes return less on repeat fetches (e.g. YC detail pages are not re-read),
    # so only overwrite fields the source actually provided.
    job.description = raw.description or job.description or ""
    job.location = (raw.location or job.location or "")[:500] or None
    job.posted_at = raw.posted_at or job.posted_at
    job.extra = {**(job.extra or {}), **{k: v for k, v in raw.extra.items() if v}}
    if raw.salary:
        job.salary_raw = raw.salary.raw[:255]
        job.salary_currency = raw.salary.currency
        job.salary_min_inr = raw.salary.min_inr
        job.salary_max_inr = raw.salary.max_inr

    job.remote_type, job.india_eligible = classify_location(
        job.location, job.description, raw.workplace, job.title, raw.strict_location
    )
    session.flush()

    previous_reason = job.filter_reason or ""
    reason = filter_reason(job)
    if reason is None and previous_reason.startswith(LLM_INDIA_PREFIX):
        # The LLM read the full post and found it closed to India; the rules cannot see that,
        # and the job is already ranked, so it would never be re-checked.
        reason = previous_reason
        job.india_eligible = False
    if reason is None:
        original = session.scalar(
            select(Job.id)
            .where(Job.dedupe_key == job.dedupe_key, Job.id < job.id)
            .order_by(Job.id)
            .limit(1)
        )
        if original is not None:
            reason = f"duplicate of job #{original}"
    job.passed_filters = reason is None
    job.filter_reason = reason
    stats.passed += reason is None
    return job


def refilter_all(session: Session) -> dict:
    """Re-apply the shared filters to every stored job (e.g. after the filter rules change).

    Exclusions that rules cannot recompute are kept: the LLM's India check and duplicates.
    """
    changed = released = 0
    for job in session.scalars(select(Job)):
        previous = job.filter_reason or ""
        if previous.startswith((LLM_INDIA_PREFIX, "duplicate of job")):
            continue
        reason = filter_reason(job)
        if reason != job.filter_reason:
            changed += 1
            released += reason is None
            job.filter_reason = reason
            job.passed_filters = reason is None
    return {"changed": changed, "now_passing": released}


def ats_boards(session: Session) -> list[tuple[str, str, str]]:
    rows = session.execute(
        select(Company.ats_type, Company.ats_slug, Company.name).where(Company.ats_type.is_not(None))
    )
    return [tuple(row) for row in rows]


def known_source_ids(session: Session, source: str) -> set[str]:
    return set(session.scalars(select(Job.source_job_id).where(Job.source == source)))
