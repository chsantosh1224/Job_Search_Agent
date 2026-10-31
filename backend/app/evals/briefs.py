"""Brief quality: deterministic grounding checks plus an LLM judge.

Faithfulness follows the RAGAS definition: the brief is split into atomic claims, each claim
is checked against the source the brief was written from, and the score is
supported claims / all claims. The source is rebuilt with the same function the writer used.
"""

import json
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.client import LLM, LLMError
from app.llm.prompts import JUDGE_SYSTEM, JUDGE_USER
from app.llm.schemas import JudgeResult
from app.models import Job, ResearchBrief, Resume
from app.ranking.graph import brief_source


def grounding_checks(brief: dict, source: str, resume: Resume) -> dict:
    """Checks that need no LLM: named people and the lead project must exist in the inputs."""
    source_lower = source.lower()
    resume_text = (resume.raw_text + " " + " ".join(c.title or "" for c in resume.chunks)).lower()
    lead = (brief.get("lead_project") or "").strip()
    return {
        "people_not_in_source": [
            p["name"] for p in brief.get("people") or []
            if p.get("name") and p["name"].lower() not in source_lower
        ],
        "lead_project_in_resume": bool(lead) and lead.lower() in resume_text,
    }


def judge_brief(llm: LLM, brief: dict, source: str) -> tuple[JudgeResult, str]:
    return llm.complete_json(
        JUDGE_SYSTEM,
        JUDGE_USER.format(source=source, brief=json.dumps(brief, indent=2, ensure_ascii=False)),
        JudgeResult,
    )


def evaluate_briefs(session: Session, llm: LLM, resume: Resume, limit: int) -> dict:
    """Judge up to `limit` most recent briefs. Returns {"metrics", "details", "errors"}."""
    rows = session.execute(
        select(ResearchBrief, Job).join(Job, Job.id == ResearchBrief.job_id)
        .where(ResearchBrief.resume_id == resume.id)
        .order_by(ResearchBrief.created_at.desc()).limit(limit)
    ).all()
    details, errors = [], []
    for brief, job in rows:
        source = brief_source(session, job, resume.id)
        checks = grounding_checks(brief.content, source, resume)
        try:
            judged, model = judge_brief(llm, brief.content, source)
        except LLMError as exc:  # includes BudgetExceeded
            errors.append(f"judge brief for job #{job.id}: {exc}")
            continue
        claims = judged.claims
        details.append({
            "job_id": job.id,
            "title": job.title,
            "company": job.company.name if job.company else None,
            "writer_model": brief.model,
            "judge_model": model,
            "faithfulness": round(sum(c.supported for c in claims) / len(claims), 3)
            if claims else None,
            "claims": len(claims),
            "unsupported": [c.claim for c in claims if not c.supported],
            "specificity": judged.specificity,
            "usefulness": judged.usefulness,
            "comment": judged.comment,
            **checks,
        })

    def avg(key: str) -> float | None:
        values = [d[key] for d in details if d[key] is not None]
        return round(mean(values), 3) if values else None

    metrics = {
        "briefs_judged": len(details),
        "faithfulness": avg("faithfulness"),
        "specificity": avg("specificity"),
        "usefulness": avg("usefulness"),
        "briefs_with_unsupported_claims": sum(bool(d["unsupported"]) for d in details),
        "people_not_in_source": sum(len(d["people_not_in_source"]) for d in details),
        "lead_project_not_in_resume": sum(not d["lead_project_in_resume"] for d in details),
    }
    return {"metrics": metrics, "details": details, "errors": errors}
