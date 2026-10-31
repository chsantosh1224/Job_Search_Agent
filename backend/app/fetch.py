"""Run every source, store its jobs, and record the run."""

import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.db import session_scope
from app.filters import is_target_role
from app.jobs_store import StoreStats, ats_boards, known_source_ids, store_job
from app.models import Company, PipelineRun
from app.normalize.text import normalize_name
from app.sources.ats import CompanyBoards
from app.sources.base import FetchContext, Source
from app.sources.hackernews import HackerNews
from app.sources.http import HttpClient
from app.sources.remote_boards import RemoteOK, Remotive
from app.sources.yc import YCJobs

log = logging.getLogger(__name__)

SEED_FILE = Path(__file__).resolve().parent.parent / "config" / "ats_companies.txt"


def all_sources() -> list[Source]:
    # Company boards run last so they include boards discovered by the other sources this run.
    return [YCJobs(is_target_role), HackerNews(), Remotive(), RemoteOK(), CompanyBoards()]


def load_seed_boards(path: Path = SEED_FILE) -> None:
    if not path.exists():
        return
    with session_scope() as session:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            ats_type, slug, name = (part.strip() for part in line.split(",", 2))
            normalized = normalize_name(name)
            company = session.scalar(select(Company).where(Company.normalized_name == normalized))
            if company is None:
                company = Company(name=name, normalized_name=normalized)
                session.add(company)
            company.ats_type, company.ats_slug = ats_type.lower(), slug


def fetch_all(only: set[str] | None = None) -> dict[str, dict]:
    """Fetch every source; returns per-source stats (a failed source has an "error" key)."""
    load_seed_boards()
    stats: dict[str, dict] = {}
    http = HttpClient(min_interval=0.5)
    try:
        for source in all_sources():
            if only and source.name not in only:
                continue
            source_stats = StoreStats()
            started = time.monotonic()
            try:
                # One transaction per source: a failing source keeps the others' jobs.
                with session_scope() as session:
                    ctx = FetchContext(
                        http=http,
                        ats_boards=ats_boards(session),
                        known_ids=known_source_ids(session, source.name),
                    )
                    for raw in source.fetch(ctx):
                        try:
                            with session.begin_nested():
                                store_job(session, raw, source_stats)
                        except SQLAlchemyError:
                            log.exception("Could not store %s job %s", source.name,
                                          raw.source_job_id)
                            source_stats.errors += 1
                stats[source.name] = source_stats.as_dict()
            except Exception as exc:
                log.exception("Source %s failed", source.name)
                stats[source.name] = {"error": f"{type(exc).__name__}: {exc}"[:500]}
            stats[source.name]["seconds"] = round(time.monotonic() - started)
            log.info("%s: %s", source.name, stats[source.name])
    finally:
        http.close()
    return stats


def fetch_status(stats: dict[str, dict]) -> str:
    failures = sum("error" in s for s in stats.values())
    return "success" if not failures else "failed" if failures == len(stats) else "partial"


def run_fetch(only: set[str] | None = None, trigger: str = "manual") -> PipelineRun:
    """Fetch only, recorded as its own run (the `jobagent fetch` command)."""
    with session_scope() as session:
        run = PipelineRun(trigger=trigger, status="running", stats={})
        session.add(run)
    stats = fetch_all(only)
    with session_scope() as session:
        run = session.merge(run)
        run.stats = stats
        run.finished_at = datetime.now(UTC)
        run.status = fetch_status(stats)
    return run
