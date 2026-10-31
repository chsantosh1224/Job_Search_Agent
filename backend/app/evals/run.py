"""Run evaluations and store them as eval_runs rows."""

from dataclasses import asdict

from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.evals.briefs import evaluate_briefs
from app.evals.ranking import compute_metrics, load_labeled
from app.llm.client import LLM, BudgetExceeded, LLMError, OpenRouterLLM
from app.models import EvalRun, Job, JobMatch
from app.ranking.context import candidate_profile, job_embedding_text
from app.ranking.graph import rank_job, save_rank
from app.resume.ingest import get_active_resume
from app.users import primary_admin


def judge_llm() -> OpenRouterLLM:
    settings = get_settings()
    return OpenRouterLLM(
        api_key=settings.openrouter_api_key,
        models=[m.strip() for m in settings.openrouter_judge_models.split(",") if m.strip()],
        min_interval=settings.llm_min_interval_seconds,
        max_calls=settings.llm_max_calls_per_run,
    )


def rank_labeled_jobs(llm: LLM, limit: int, embedder=None) -> dict:
    """LLM-rank labeled jobs the daily run skipped (e.g. below the similarity cut-off), so the
    eval covers every label, not just the jobs the pipeline already liked."""
    from app.embeddings import get_embedder

    ranked, errors = 0, []
    with session_scope() as session:
        admin = primary_admin(session)
        resume = get_active_resume(session, admin.id) if admin else None
        if resume is None:
            return {"ranked": 0, "errors": ["the admin has no active resume"]}
        pending = [i.job_id for i in load_labeled(session) if not i.ranked][:limit]
        profile = candidate_profile(resume)
        for job_id in pending:
            job = session.get(Job, job_id)
            if job.embedding is None:
                job.embedding = (embedder or get_embedder()).embed([job_embedding_text(job)])[0]
            match = session.scalar(select(JobMatch).where(JobMatch.job_id == job_id,
                                                          JobMatch.resume_id == resume.id))
            similarity = match.similarity if match else float(
                1 - session.scalar(select(Job.embedding.cosine_distance(resume.embedding))
                                   .where(Job.id == job_id)))
            try:
                result, model = rank_job(session, llm, resume, job, profile, admin.about)
            except BudgetExceeded:
                break
            except LLMError as exc:
                errors.append(f"rank job #{job_id}: {exc}")
                continue
            save_rank(session, job, resume.id, similarity, result, model)
            session.commit()
            ranked += 1
    return {"ranked": ranked, "errors": errors}


def run_ranking_eval() -> EvalRun:
    """Pure database computation; no LLM calls."""
    with session_scope() as session:
        items = load_labeled(session)
        metrics = compute_metrics(items, get_settings().brief_min_score)
        run = EvalRun(kind="ranking", metrics=metrics, details=[asdict(i) for i in items])
        session.add(run)
        session.flush()
        return run


def run_brief_eval(llm: LLM, limit: int) -> EvalRun | None:
    with session_scope() as session:
        admin = primary_admin(session)
        resume = get_active_resume(session, admin.id) if admin else None
        if resume is None:
            return None
        result = evaluate_briefs(session, llm, resume, limit)
        run = EvalRun(kind="briefs", metrics={**result["metrics"], "errors": result["errors"]},
                      details=result["details"])
        session.add(run)
        session.flush()
        return run
