"""Rank jobs for each user within the daily AI limits."""

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select

from app.config import Settings, get_settings
from app.db import session_scope
from app.embeddings import Embedder, get_embedder
from app.llm.client import LLM, LLMError, OpenRouterLLM
from app.models import PipelineRun, Resume, User
from app.ranking.graph import build_graph
from app.usage import calls_today, record, usage_row

LLMFactory = Callable[[int], LLM]  # max calls -> client


def default_llm(settings: Settings, max_calls: int | None = None) -> OpenRouterLLM:
    return OpenRouterLLM(
        api_key=settings.openrouter_api_key,
        models=[m.strip() for m in settings.openrouter_models.split(",") if m.strip()],
        min_interval=settings.llm_min_interval_seconds,
        max_calls=max_calls if max_calls is not None else settings.llm_max_calls_per_run,
    )


def rank_users(user_ids: list[int] | None = None, llm_factory: LLMFactory | None = None,
               embedder: Embedder | None = None, limit: int | None = None,
               briefs: int | None = None) -> dict:
    """Rank new jobs for each active user with a resume (or just `user_ids`).

    Each user gets what is left of their daily limits, and the run stops for everyone once the
    overall daily cap is used. `limit` / `briefs` lower the per-user numbers for a trial run.
    Returns {"stats": ..., "errors": [...]}.
    """
    settings = get_settings()
    factory = llm_factory or (lambda max_calls: default_llm(settings, max_calls))
    per_user: dict[str, dict] = {}
    errors: list[str] = []

    with session_scope() as session:
        query = (select(User.id, Resume.id).join(Resume, Resume.user_id == User.id)
                 .where(User.is_active.is_(True), Resume.is_active.is_(True))
                 .order_by(User.id))
        if user_ids is not None:
            query = query.where(User.id.in_(user_ids))
        targets = session.execute(query).all()

    for user_id, resume_id in targets:
        key = f"user {user_id}"
        with session_scope() as session:
            user = session.get(User, user_id)
            used = usage_row(session, user_id)
            global_left = settings.llm_daily_cap - calls_today(session)
            rank_left = settings.user_daily_rank_limit - used.ranked
            brief_left = settings.user_daily_brief_limit - used.briefs
            about, min_usd = user.about, user.min_salary_usd
        if limit is not None:
            rank_left = min(rank_left, limit)
        if briefs is not None:
            brief_left = min(brief_left, briefs)
        if global_left <= 0:
            per_user[key] = {"skipped": "overall daily AI cap reached"}
            break
        if rank_left <= 0 and brief_left <= 0:
            per_user[key] = {"skipped": "daily limit reached"}
            continue

        try:
            llm = factory(min(settings.llm_max_calls_per_run, global_left))
        except LLMError as exc:
            return {"stats": {"users": len(targets), "per_user": per_user},
                    "errors": [*errors, str(exc)]}
        # The graph holds the LLM in a closure; built per user so each gets its own budget.
        graph = build_graph(embedder or get_embedder(), llm, settings)
        result = graph.invoke({
            "resume_id": resume_id, "about": about,
            "min_salary_inr": min_usd * settings.usd_to_inr if min_usd else None,
            "rank_limit": max(rank_left, 0), "brief_limit": max(brief_left, 0),
            "stats": {}, "errors": [],
        })
        stats = {**result["stats"], "llm_calls": llm.calls}
        per_user[key] = stats
        errors.extend(f"{key}: {e}" for e in result["errors"])
        with session_scope() as session:
            record(session, user_id, calls=llm.calls, ranked=stats.get("ranked", 0),
                   briefs=stats.get("briefs", 0))

    total_calls = sum(s.get("llm_calls", 0) for s in per_user.values())
    return {"stats": {"users": len(targets), "llm_calls": total_calls, "per_user": per_user},
            "errors": errors[:50]}


def run_rank(trigger: str = "manual", user_ids: list[int] | None = None,
             limit: int | None = None, briefs: int | None = None) -> PipelineRun:
    """Rank only, recorded as its own run (the `jobagent rank` command)."""
    with session_scope() as session:
        run = PipelineRun(trigger=trigger, status="running", stats={},
                          user_id=user_ids[0] if user_ids and len(user_ids) == 1 else None)
        session.add(run)

    status, result = "success", {"stats": {}, "errors": []}
    try:
        result = rank_users(user_ids, limit=limit, briefs=briefs)
        if result["errors"]:
            status = "partial"
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}"[:500])
        status = "failed"
        raise
    finally:
        with session_scope() as session:
            run = session.merge(run)
            run.stats = {"rank": result["stats"], "errors": result["errors"]}
            run.status = status
            run.finished_at = datetime.now(UTC)
    return run
