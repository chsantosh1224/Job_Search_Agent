"""The full daily pipeline (fetch -> rank -> digest) and the worker that runs it.

Runs are rows in pipeline_runs. The dashboard's "Run now" button only inserts a "queued" row;
the worker executes queued rows and starts the scheduled daily run. A Postgres advisory lock
makes sure two runs never overlap, even if two workers were started by mistake.
"""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text, update

from app.config import get_settings
from app.db import engine, session_scope
from app.digest import send_digests
from app.fetch import fetch_all
from app.models import PipelineRun
from app.ranking.run import rank_users

log = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
PIPELINE_LOCK_ID = 727_001  # arbitrary, app-wide
ACTIVE_STATUSES = ("queued", "running")
STALE_AFTER = timedelta(hours=3)
POLL_SECONDS = 15


def execute_run(run_id: int, fetch: Callable = fetch_all, rank: Callable = rank_users,
                digest: Callable = send_digests) -> PipelineRun:
    """Execute one queued run. Steps are injectable for tests."""
    with engine.connect() as lock_conn:
        if not lock_conn.scalar(text("SELECT pg_try_advisory_lock(:id)"),
                                {"id": PIPELINE_LOCK_ID}):
            return _finish(run_id, "skipped", {"errors": ["another run is in progress"]})
        try:
            return _execute(run_id, fetch, rank, digest)
        finally:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": PIPELINE_LOCK_ID})


def _execute(run_id: int, fetch: Callable, rank: Callable, digest: Callable) -> PipelineRun:
    """A user's run only ranks for that user; a global run fetches, ranks everyone, emails."""
    with session_scope() as session:
        run = session.get(PipelineRun, run_id)
        run.status = "running"
        run.started_at = datetime.now(UTC)
        user_id = run.user_id

    stats: dict = {"errors": []}
    try:
        if user_id is None:
            stats["fetch"] = fetch()
            _save_progress(run_id, stats)
        ranked = rank([user_id] if user_id else None)
        stats["rank"] = ranked["stats"]
        stats["errors"].extend(ranked["errors"])
        _save_progress(run_id, stats)
        if user_id is None:
            with session_scope() as session:
                stats["digest"] = digest(session)
    except Exception as exc:  # recorded on the run; the worker keeps going
        log.exception("Run #%s failed", run_id)
        stats["errors"].append(f"{type(exc).__name__}: {exc}"[:500])
        return _finish(run_id, "failed", stats)

    fetch_failed = any("error" in s for s in stats.get("fetch", {}).values())
    status = "partial" if stats["errors"] or fetch_failed else "success"
    return _finish(run_id, status, stats)


def _save_progress(run_id: int, stats: dict) -> None:
    with session_scope() as session:
        session.get(PipelineRun, run_id).stats = dict(stats)


def _finish(run_id: int, status: str, stats: dict) -> PipelineRun:
    with session_scope() as session:
        run = session.get(PipelineRun, run_id)
        run.status = status
        run.stats = stats
        run.finished_at = datetime.now(UTC)
        return run


def queue_run(trigger: str, user_id: int | None = None) -> PipelineRun | None:
    """Queue a run. Returns None if an equivalent one is already pending.

    Global runs (fetch + rank everyone): at most one queued or running.
    A user's ranking run: at most one queued per user.
    """
    with session_scope() as session:
        # Serialize concurrent clicks / uploads for the rest of this transaction.
        session.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": PIPELINE_LOCK_ID + 1})
        if user_id is None:
            pending = select(PipelineRun.id).where(PipelineRun.user_id.is_(None),
                                                   PipelineRun.status.in_(ACTIVE_STATUSES))
        else:
            pending = select(PipelineRun.id).where(PipelineRun.user_id == user_id,
                                                   PipelineRun.status == "queued")
        if session.scalar(pending.limit(1)) is not None:
            return None
        run = PipelineRun(trigger=trigger, user_id=user_id, status="queued", stats={})
        session.add(run)
        session.flush()
        return run


def next_daily_run(now: datetime, daily_time: str) -> datetime:
    """Next occurrence of HH:MM India time after `now` (an aware datetime)."""
    hour, minute = (int(part) for part in daily_time.split(":"))
    local = now.astimezone(IST)
    target = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= local:
        target += timedelta(days=1)
    return target


def fail_stale_runs(now: datetime | None = None) -> int:
    """Runs left queued/running by a crashed worker would block "Run now" forever."""
    cutoff = (now or datetime.now(UTC)) - STALE_AFTER
    with session_scope() as session:
        result = session.execute(
            update(PipelineRun)
            .where(PipelineRun.status.in_(ACTIVE_STATUSES), PipelineRun.started_at < cutoff)
            .values(status="failed", finished_at=func.now(),
                    stats={"errors": ["worker stopped before the run finished"]})
        )
        return result.rowcount


def next_queued_run() -> int | None:
    with session_scope() as session:
        return session.scalar(
            select(PipelineRun.id).where(PipelineRun.status == "queued")
            .order_by(PipelineRun.id).limit(1)
        )


def run_worker() -> None:  # pragma: no cover - long-running loop
    settings = get_settings()
    stale = fail_stale_runs()
    if stale:
        log.warning("Marked %d stale run(s) as failed", stale)
    due = next_daily_run(datetime.now(UTC), settings.daily_run_time_ist)
    log.info("Worker started; next daily run %s IST", due.strftime("%Y-%m-%d %H:%M"))
    while True:
        if datetime.now(UTC) >= due:
            if queue_run("scheduled") is None:
                log.info("Daily run skipped: another run is active")
            due = next_daily_run(datetime.now(UTC), settings.daily_run_time_ist)
            log.info("Next daily run %s IST", due.strftime("%Y-%m-%d %H:%M"))
        run_id = next_queued_run()
        if run_id is not None:
            log.info("Starting run #%d", run_id)
            run = execute_run(run_id)
            log.info("Run #%d finished: %s", run_id, run.status)
            continue
        time.sleep(POLL_SECONDS)
