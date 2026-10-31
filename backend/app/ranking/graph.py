"""LangGraph pipeline that ranks new jobs for one resume and writes research briefs.

    load_candidates -> embed_jobs -> prefilter -> rank -> select_for_briefs -> write_briefs

Cheap steps run on every candidate; LLM steps only on the shortlist. Jobs that are not ranked
in this run (over the user's daily limit or out of budget) stay candidates for the next run.
"""

import logging
from typing import TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import session_scope
from app.embeddings import Embedder
from app.filters import LLM_INDIA_PREFIX
from app.llm.client import LLM, BudgetExceeded, LLMError
from app.llm.prompts import BRIEF_SYSTEM, BRIEF_USER, RANK_SYSTEM, RANK_USER
from app.llm.schemas import RankResult, ResearchBriefContent
from app.models import Job, JobMatch, ResearchBrief, Resume
from app.ranking.context import (
    MAX_DESCRIPTION_CHARS,
    candidate_profile,
    extra_text,
    job_embedding_text,
    matching_chunks,
    salary_text,
)
from app.resume.ingest import embed_resume

log = logging.getLogger(__name__)


def rank_job(session: Session, llm: LLM, resume: Resume, job: Job, profile: str,
             about: str = "") -> tuple[RankResult, str]:
    """One LLM ranking call for one job. Raises LLMError / BudgetExceeded."""
    prompt = RANK_USER.format(
        profile=profile,
        about=about or "None given.",
        matching_chunks=matching_chunks(session, resume.id, job.embedding),
        title=job.title,
        company=job.company.name if job.company else "Unknown",
        location=job.location or "Not stated",
        remote_type=job.remote_type.value,
        salary=salary_text(job),
        extra=extra_text(job),
        description=job.description[:MAX_DESCRIPTION_CHARS],
    )
    return llm.complete_json(RANK_SYSTEM, prompt, RankResult)


def save_rank(session: Session, job: Job, resume_id: int, similarity: float,
              result: RankResult, model: str) -> bool:
    """Store (or replace) the job's match; apply the LLM's India check.

    Returns True when the job was excluded as not open to India.
    """
    match = session.scalar(select(JobMatch).where(JobMatch.job_id == job.id,
                                                  JobMatch.resume_id == resume_id))
    if match is None:
        match = JobMatch(job_id=job.id, resume_id=resume_id)
        session.add(match)
    match.similarity = similarity
    match.tier, match.fit_score = result.tier, result.fit_score
    match.reasons, match.gaps, match.model = result.reasons, result.gaps, model
    if result.india_eligibility == "no":
        job.india_eligible = False
        job.passed_filters = False
        job.filter_reason = f"{LLM_INDIA_PREFIX}: {result.eligibility_evidence or ''}"[:255]
        return True
    if result.india_eligibility == "yes" and job.india_eligible is None:
        job.india_eligible = True
    return False


def brief_source(session: Session, job: Job, resume_id: int) -> str:
    """Everything the brief writer sees; the brief judge checks claims against the same text."""
    company = job.company
    return BRIEF_USER.format(
        matching_chunks=matching_chunks(session, resume_id, job.embedding),
        title=job.title,
        location=job.location or "Not stated",
        salary=salary_text(job),
        url=job.url,
        description=job.description[:MAX_DESCRIPTION_CHARS],
        company=company.name if company else "Unknown",
        website=(company.website if company else None) or "Not stated",
        company_description=(company.description if company else None) or "Not stated",
        extra=extra_text(job),
    )


class RankState(TypedDict, total=False):
    # Inputs
    resume_id: int
    about: str  # the user's note for the AI
    min_salary_inr: float | None  # the user's minimum; jobs with unknown salary still qualify
    rank_limit: int  # jobs this user may still have ranked today
    brief_limit: int  # briefs this user may still get today
    # Working state
    candidates: list[int]
    shortlist: list[int]
    similarity: dict[int, float]  # job id -> cosine similarity to the resume
    to_brief: list[int]
    stats: dict
    errors: list[str]


def build_graph(embedder: Embedder, llm: LLM, settings: Settings):
    def load_candidates(state: RankState) -> RankState:
        with session_scope() as session:
            resume = session.get(Resume, state["resume_id"])
            if resume.embedding is None:  # uploaded through the dashboard, not embedded yet
                embed_resume(resume, embedder)
            already_matched = exists().where(JobMatch.job_id == Job.id,
                                             JobMatch.resume_id == resume.id)
            query = select(Job.id).where(Job.passed_filters.is_(True), ~already_matched)
            if state.get("min_salary_inr"):
                query = query.where(or_(Job.salary_max_inr.is_(None),
                                        Job.salary_max_inr >= state["min_salary_inr"]))
            candidates = list(session.scalars(query))
        return {"candidates": candidates,
                "stats": {**state["stats"], "candidates": len(candidates)}}

    def embed_jobs(state: RankState) -> RankState:
        with session_scope() as session:
            jobs = list(session.scalars(
                select(Job).where(Job.id.in_(state["candidates"]), Job.embedding.is_(None))
            ))
            for job, vector in zip(
                jobs, embedder.embed([job_embedding_text(j) for j in jobs]), strict=True
            ):
                job.embedding = vector
        return {"stats": {**state["stats"], "embedded": len(jobs)}}

    def prefilter(state: RankState) -> RankState:
        with session_scope() as session:
            resume = session.get(Resume, state["resume_id"])
            similarity = (1 - Job.embedding.cosine_distance(resume.embedding)).label("similarity")
            rows = session.execute(
                select(Job.id, similarity)
                .where(Job.id.in_(state["candidates"]))
                .order_by(similarity.desc())
            ).all()
            shortlist, below = [], 0
            for job_id, score in rows:
                if score < settings.min_similarity:
                    # Recorded so the job is not reconsidered every run.
                    session.add(JobMatch(
                        job_id=job_id, resume_id=resume.id, similarity=score, tier=None,
                        reasons=[f"Low similarity to resume ({score:.2f})"], gaps=[],
                    ))
                    below += 1
                elif len(shortlist) < state["rank_limit"]:
                    shortlist.append(job_id)
        return {"shortlist": shortlist,
                "similarity": {job_id: float(score) for job_id, score in rows},
                "stats": {**state["stats"], "shortlisted": len(shortlist), "below_cutoff": below}}

    def rank(state: RankState) -> RankState:
        ranked = deferred = not_india = 0
        errors = list(state["errors"])
        reserve = state["brief_limit"]  # keep enough budget for the briefs
        with session_scope() as session:
            resume = session.get(Resume, state["resume_id"])
            profile = candidate_profile(resume)
            for job_id in state["shortlist"]:
                if llm.calls >= settings.llm_max_calls_per_run - reserve:
                    deferred += 1
                    continue
                job = session.get(Job, job_id)
                try:
                    result, model = rank_job(session, llm, resume, job, profile,
                                             state.get("about", ""))
                except BudgetExceeded:
                    deferred += 1
                    continue
                except LLMError as exc:
                    errors.append(f"rank job #{job_id}: {exc}")
                    continue
                not_india += save_rank(session, job, resume.id, state["similarity"][job_id],
                                       result, model)
                session.commit()  # keep each ranked job even if a later one fails
                ranked += 1
        return {"errors": errors, "stats": {**state["stats"], "ranked": ranked,
                                            "deferred": deferred, "not_india": not_india}}

    def select_for_briefs(state: RankState) -> RankState:
        if state["brief_limit"] <= 0:
            return {"to_brief": []}
        with session_scope() as session:
            has_brief = exists().where(ResearchBrief.job_id == JobMatch.job_id,
                                       ResearchBrief.resume_id == state["resume_id"])
            to_brief = list(session.scalars(
                select(JobMatch.job_id)
                .join(Job, Job.id == JobMatch.job_id)
                .where(JobMatch.resume_id == state["resume_id"],
                       JobMatch.tier.is_not(None),
                       JobMatch.fit_score >= settings.brief_min_score,
                       Job.passed_filters.is_(True),
                       ~has_brief)
                .order_by(JobMatch.fit_score.desc())
                .limit(state["brief_limit"])
            ))
        return {"to_brief": to_brief}

    def write_briefs(state: RankState) -> RankState:
        written = 0
        errors = list(state["errors"])
        with session_scope() as session:
            for job_id in state["to_brief"]:
                prompt = brief_source(session, session.get(Job, job_id), state["resume_id"])
                try:
                    brief, model = llm.complete_json(BRIEF_SYSTEM, prompt, ResearchBriefContent)
                except LLMError as exc:  # includes BudgetExceeded
                    errors.append(f"brief job #{job_id}: {exc}")
                    continue
                session.add(ResearchBrief(job_id=job_id, resume_id=state["resume_id"],
                                          content=brief.model_dump(), model=model))
                session.commit()
                written += 1
        return {"errors": errors, "stats": {**state["stats"], "briefs": written}}

    graph = StateGraph(RankState)
    for name, node in [("load_candidates", load_candidates), ("embed_jobs", embed_jobs),
                       ("prefilter", prefilter), ("rank", rank),
                       ("select_for_briefs", select_for_briefs), ("write_briefs", write_briefs)]:
        graph.add_node(name, node)
    graph.set_entry_point("load_candidates")
    # With no new candidates, still brief earlier-ranked jobs that lack one.
    graph.add_conditional_edges(
        "load_candidates",
        lambda s: "embed_jobs" if s["candidates"] else "select_for_briefs",
    )
    graph.add_edge("embed_jobs", "prefilter")
    graph.add_conditional_edges(
        "prefilter", lambda s: "rank" if s["shortlist"] else "select_for_briefs"
    )
    graph.add_edge("rank", "select_for_briefs")
    graph.add_conditional_edges(
        "select_for_briefs", lambda s: "write_briefs" if s["to_brief"] else END
    )
    graph.add_edge("write_briefs", END)
    return graph.compile()
