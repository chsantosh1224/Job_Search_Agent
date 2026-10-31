"""Labels for the eval set, live ranking metrics, and eval history."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.auth import require_admin
from app.api.deps import SessionDep
from app.config import get_settings
from app.evals.ranking import compute_metrics, load_labeled
from app.evals.run import run_ranking_eval
from app.filters import LLM_INDIA_PREFIX
from app.models import EvalLabel, EvalRun, Job

# Evals measure the system's quality: admin only.
router = APIRouter(prefix="/api", tags=["evals"], dependencies=[Depends(require_admin)])

LABEL_GOAL = 30


class LabelIn(BaseModel):
    is_good_fit: bool
    expected_tier: Annotated[int | None, Field(ge=1, le=3)] = None
    notes: str = ""


def _label_dict(label: EvalLabel | None) -> dict | None:
    if label is None:
        return None
    return {"is_good_fit": label.is_good_fit, "expected_tier": label.expected_tier,
            "notes": label.notes}


def _run_dict(run: EvalRun, with_details: bool = False) -> dict:
    data = {"id": run.id, "kind": run.kind, "created_at": run.created_at, "metrics": run.metrics}
    if with_details:
        data["details"] = run.details
    return data


@router.get("/evals")
def evals_overview(session: SessionDep) -> dict:
    items = load_labeled(session)
    history = session.scalars(select(EvalRun).order_by(EvalRun.id.desc()).limit(20)).all()
    latest_briefs = next((r for r in history if r.kind == "briefs"), None)
    return {
        "label_goal": LABEL_GOAL,
        "ranking": compute_metrics(items, get_settings().brief_min_score),
        "latest_briefs": _run_dict(latest_briefs, with_details=True) if latest_briefs else None,
        "history": [_run_dict(r) for r in history],
    }


@router.get("/evals/queue")
def label_queue(session: SessionDep,
                limit: Annotated[int, Query(le=100)] = 20) -> list[dict]:
    """Unlabeled jobs worth labeling, shown blind: no AI tier or score, so labels stay
    independent of the ranking they will grade."""
    labeled = select(EvalLabel.job_id)
    jobs = session.scalars(
        select(Job)
        .where(Job.id.not_in(labeled),
               or_(Job.passed_filters.is_(True), Job.filter_reason.startswith(LLM_INDIA_PREFIX)))
        .order_by(Job.posted_at.desc().nulls_last())
        .limit(limit)
    )
    return [
        {"id": j.id, "title": j.title, "company": j.company.name if j.company else None,
         "location": j.location, "url": j.url,
         "salary_max_lpa": round(j.salary_max_inr / 1e5) if j.salary_max_inr else None,
         "snippet": j.description[:700]}
        for j in jobs
    ]


@router.put("/jobs/{job_id}/label")
def set_label(job_id: int, body: LabelIn, session: SessionDep) -> dict:
    if session.get(Job, job_id) is None:
        raise HTTPException(404, "Job not found")
    label = session.scalar(select(EvalLabel).where(EvalLabel.job_id == job_id))
    if label is None:
        label = EvalLabel(job_id=job_id)
        session.add(label)
    label.is_good_fit = body.is_good_fit
    label.expected_tier = body.expected_tier if body.is_good_fit else None
    label.notes = body.notes
    return _label_dict(label)


@router.delete("/jobs/{job_id}/label", status_code=204)
def delete_label(job_id: int, session: SessionDep) -> None:
    label = session.scalar(select(EvalLabel).where(EvalLabel.job_id == job_id))
    if label is not None:
        session.delete(label)


@router.post("/evals/ranking", status_code=201)
def snapshot_ranking_eval() -> dict:
    """Save the current ranking metrics to the history (no LLM calls)."""
    return _run_dict(run_ranking_eval())


def label_for(session: Session, job_id: int) -> dict | None:
    return _label_dict(session.scalar(select(EvalLabel).where(EvalLabel.job_id == job_id)))
