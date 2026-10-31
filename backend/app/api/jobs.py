"""Jobs (shared) seen through the signed-in user's ranking, brief and tracker."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.api.auth import AdminDep, UserDep
from app.api.deps import SessionDep
from app.api.evals import label_for
from app.config import get_settings
from app.models import (
    Application,
    ApplicationStatus,
    Job,
    JobMatch,
    PipelineRun,
    RemoteType,
    ResearchBrief,
    User,
)
from app.resume.ingest import get_active_resume

router = APIRouter(prefix="/api", tags=["jobs"])


class View(StrEnum):
    MATCHES = "matches"  # ranked into a tier
    OTHER = "other"  # passed filters, not ranked yet or not a fit
    TRACKED = "tracked"  # has an application status beyond "new"
    FILTERED = "filtered"  # failed a hard filter or the LLM India check


class Region(StrEnum):
    WORLDWIDE = "worldwide"
    INDIA = "india"
    UNSPECIFIED = "unspecified"  # remote, region not stated


REGION_TYPES = {
    Region.WORLDWIDE: RemoteType.REMOTE_GLOBAL,
    Region.INDIA: RemoteType.REMOTE_INDIA,
    Region.UNSPECIFIED: RemoteType.REMOTE_UNSPECIFIED,
}


class JobItem(BaseModel):
    id: int
    title: str
    company: str | None
    source: str
    url: str
    location: str | None
    remote_type: str
    india_eligible: bool | None
    salary_min_usd: int | None
    salary_max_usd: int | None
    posted_at: datetime | None
    filter_reason: str | None
    tier: int | None
    fit_score: int | None
    ranked: bool
    has_brief: bool
    status: str | None


class JobDetail(JobItem):
    description: str
    salary_raw: str | None
    company_website: str | None
    company_description: str | None
    yc_batch: str | None
    extra: dict
    similarity: float | None
    reasons: list[str]
    gaps: list[str]
    model: str | None
    brief: dict | None
    brief_model: str | None
    notes: str
    label: dict | None


class ApplicationUpdate(BaseModel):
    status: ApplicationStatus
    notes: str = ""


def _usd(inr: int | None) -> int | None:
    return round(inr / get_settings().usd_to_inr) if inr else None


def _item(job: Job, match: JobMatch | None, application: Application | None,
          has_brief: bool) -> dict:
    return {
        "id": job.id, "title": job.title, "company": job.company.name if job.company else None,
        "source": job.source, "url": job.url, "location": job.location,
        "remote_type": job.remote_type.value, "india_eligible": job.india_eligible,
        "salary_min_usd": _usd(job.salary_min_inr), "salary_max_usd": _usd(job.salary_max_inr),
        "posted_at": job.posted_at, "filter_reason": job.filter_reason,
        "tier": match.tier if match else None,
        "fit_score": match.fit_score if match else None,
        "ranked": bool(match and match.model),
        "has_brief": has_brief,
        "status": application.status.value if application else None,
    }


def _query(session: Session, user: User):
    resume = get_active_resume(session, user.id)
    resume_id = resume.id if resume else -1
    match = aliased(JobMatch)
    has_brief = select(ResearchBrief.id).where(ResearchBrief.job_id == Job.id,
                                               ResearchBrief.resume_id == resume_id).exists()
    query = (
        select(Job, match, Application, has_brief.label("has_brief"))
        .outerjoin(match, and_(match.job_id == Job.id, match.resume_id == resume_id))
        .outerjoin(Application, and_(Application.job_id == Job.id,
                                     Application.user_id == user.id))
    )
    return query, match, resume_id


def salary_condition(min_usd: int | None, max_usd: int | None, include_unknown: bool):
    """Job salary range overlaps the requested USD range; unknown salaries are optional."""
    rate = get_settings().usd_to_inr
    known = Job.salary_max_inr.is_not(None)
    conditions = [known]
    if min_usd is not None:
        conditions.append(Job.salary_max_inr >= min_usd * rate)
    if max_usd is not None:
        conditions.append(func.coalesce(Job.salary_min_inr, Job.salary_max_inr) <= max_usd * rate)
    in_range = and_(*conditions)
    return or_(in_range, ~known) if include_unknown else in_range


@router.get("/jobs", response_model=list[JobItem])
def list_jobs(
    user: UserDep,
    session: SessionDep,
    view: View = View.MATCHES,
    q: str | None = None,
    tier: Annotated[int | None, Query(ge=1, le=3)] = None,
    status: ApplicationStatus | None = None,
    salary_min_usd: Annotated[int | None, Query(ge=0)] = None,
    salary_max_usd: Annotated[int | None, Query(ge=0)] = None,
    include_unknown_salary: bool = True,
    region: Annotated[list[Region] | None, Query()] = None,
    limit: Annotated[int, Query(le=1000)] = 300,
) -> list[dict]:
    query, match, _ = _query(session, user)
    if view == View.MATCHES:
        query = query.where(Job.passed_filters.is_(True), match.tier.is_not(None)).order_by(
            match.tier, match.fit_score.desc())
    elif view == View.OTHER:
        query = query.where(Job.passed_filters.is_(True), match.tier.is_(None)).order_by(
            Job.posted_at.desc().nulls_last())
    elif view == View.TRACKED:
        query = query.where(Application.status != ApplicationStatus.NEW).order_by(
            Application.updated_at.desc())
    else:
        query = query.where(Job.passed_filters.is_(False)).order_by(
            Job.posted_at.desc().nulls_last())

    if view != View.FILTERED:  # filtered-out jobs are listed with their reason, unfiltered
        regions = region or list(Region)
        query = query.where(Job.remote_type.in_([REGION_TYPES[r] for r in regions]))
        query = query.where(salary_condition(salary_min_usd, salary_max_usd,
                                             include_unknown_salary))
    if q:
        pattern = f"%{q}%"
        query = query.where(or_(Job.title.ilike(pattern), Job.description.ilike(pattern)))
    if tier:
        query = query.where(match.tier == tier)
    if status:
        query = query.where(Application.status == status)
    rows = session.execute(query.limit(limit)).all()
    return [_item(job, m, app, brief) for job, m, app, brief in rows]


def _detail(session: Session, user: User, job_id: int) -> dict:
    query, _, resume_id = _query(session, user)
    row = session.execute(query.where(Job.id == job_id)).first()
    if row is None:
        raise HTTPException(404, "Job not found")
    job, m, application, has_brief = row
    brief = session.scalar(select(ResearchBrief).where(ResearchBrief.job_id == job_id,
                                                       ResearchBrief.resume_id == resume_id))
    company = job.company
    return {
        **_item(job, m, application, has_brief),
        "description": job.description, "salary_raw": job.salary_raw,
        "company_website": company.website if company else None,
        "company_description": company.description if company else None,
        "yc_batch": company.yc_batch if company else None,
        "extra": job.extra or {},
        "similarity": m.similarity if m else None,
        "reasons": m.reasons if m else [], "gaps": m.gaps if m else [],
        "model": m.model if m else None,
        "brief": brief.content if brief else None,
        "brief_model": brief.model if brief else None,
        "notes": application.notes if application else "",
        "label": label_for(session, job_id) if user.is_admin else None,
    }


@router.get("/jobs/{job_id}", response_model=JobDetail)
def get_job(job_id: int, user: UserDep, session: SessionDep) -> dict:
    return _detail(session, user, job_id)


@router.put("/jobs/{job_id}/application", response_model=JobDetail)
def update_application(job_id: int, body: ApplicationUpdate, user: UserDep,
                       session: SessionDep) -> dict:
    if session.get(Job, job_id) is None:
        raise HTTPException(404, "Job not found")
    application = session.scalar(select(Application).where(Application.job_id == job_id,
                                                           Application.user_id == user.id))
    if application is None:
        application = Application(job_id=job_id, user_id=user.id)
        session.add(application)
    application.status = body.status
    application.notes = body.notes
    session.flush()
    session.expire_all()  # pick up the updated_at set by the database
    return _detail(session, user, job_id)


@router.post("/runs", status_code=202)
def run_now(admin: AdminDep) -> dict:
    """Queue a full pipeline run (fetch + rank everyone); the worker picks it up in seconds."""
    from app.pipeline import queue_run

    run = queue_run("manual")
    if run is None:
        raise HTTPException(409, "A run is already queued or in progress")
    return {"id": run.id, "status": run.status}


def _run_dict(run: PipelineRun) -> dict:
    return {"id": run.id, "trigger": run.trigger, "status": run.status,
            "started_at": run.started_at, "finished_at": run.finished_at, "stats": run.stats,
            "user_id": run.user_id}


@router.get("/summary")
def summary(user: UserDep, session: SessionDep) -> dict:
    resume = get_active_resume(session, user.id)
    resume_id = resume.id if resume else -1
    tiers = dict(session.execute(
        select(JobMatch.tier, func.count())
        .join(Job, Job.id == JobMatch.job_id)
        .where(JobMatch.resume_id == resume_id, JobMatch.tier.is_not(None),
               Job.passed_filters.is_(True))
        .group_by(JobMatch.tier)
    ).all())
    statuses = dict(session.execute(
        select(Application.status, func.count()).where(Application.user_id == user.id)
        .group_by(Application.status)).all())
    # Admins see every run; everyone else only their own ranking runs.
    runs_query = select(PipelineRun).order_by(PipelineRun.id.desc()).limit(10)
    if not user.is_admin:
        runs_query = runs_query.where(PipelineRun.user_id == user.id)
    return {
        "jobs_total": session.scalar(select(func.count()).select_from(Job)),
        "jobs_passed": session.scalar(
            select(func.count()).select_from(Job).where(Job.passed_filters.is_(True))),
        "briefs": session.scalar(select(func.count()).select_from(ResearchBrief)
                                 .where(ResearchBrief.resume_id == resume_id)),
        "tiers": {str(tier): count for tier, count in tiers.items()},
        "applications": {s.value: count for s, count in statuses.items()},
        "resume": resume.filename if resume else None,
        "daily_run_time_ist": get_settings().daily_run_time_ist,
        "runs": [_run_dict(r) for r in session.scalars(runs_query)],
    }
