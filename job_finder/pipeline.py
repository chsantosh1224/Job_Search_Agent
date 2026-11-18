"""The full run (discover → boards → liveness → export), shared by the CLI and the web UI.

Every step reports progress through `emit(event: dict)`. Event types:
  run_start / run_done / run_error
  stage        {stage: discover|boards|liveness|export, state: start|done|skipped, ...counts}
  exa          {state: start|done|error, run, query, index, total, results?, candidates?}
  board        {ats, board_id, jobs, match, closed, error, done, total}
  check        {key, title, company, status, done, total}
"""

import asyncio
import logging
import os
import time
from collections.abc import Callable

import httpx

import ats
import exa_search
import liveness
from ats import Board, job_key
from export import export as export_jobs
from filters import Filters
from models import Job
from settings import Config
from store import Store, now

log = logging.getLogger("job_finder")
UA = "Mozilla/5.0 (compatible; job-link-finder/1.0)"
Emit = Callable[[dict], None]


def _noop(_: dict) -> None:
    pass


def hit_to_job(hit: exa_search.Hit) -> Job:
    s = hit.summary
    key, board = job_key(hit.url)
    return Job(
        key=key,
        url=hit.url,
        title=s.job_title or hit.title,
        company=s.company or (board.board_id if board else ""),
        location=s.location,
        work_mode=s.work_mode,
        experience_required=s.experience_required,
        posted_date=exa_search.parse_summary_date(s.posted_date) or hit.published_date,
        apply_url=s.apply_url or hit.url,
        source=f"exa:{hit.run}",
        ats=board.ats if board else "",
        board_id=board.board_id if board else "",
        status="unknown",
    )


def ingest_hits(store: Store, filters: Filters, hits: list[exa_search.Hit]) -> set[str]:
    """Store matching open postings; register every ATS board seen (even on non-posting pages)."""
    kept: set[str] = set()
    for hit in hits:
        if board := ats.detect_board(hit.url):
            store.add_company(board)
        if not hit.is_candidate:
            continue
        job = hit_to_job(hit)
        if filters.keep(job, extra_location_text=" ".join(hit.highlights)):
            store.upsert_job(job)
            kept.add(job.key)
    store.commit()
    return kept


async def expand_boards(
    store: Store, filters: Filters, client: httpx.AsyncClient, concurrency: int, emit: Emit = _noop
) -> set[str]:
    """Phase 2: pull every known board; keep matching jobs; close jobs that left the board."""
    sem = asyncio.Semaphore(concurrency)
    confirmed: set[str] = set()
    ts = now()
    boards = store.companies()

    async def one(board: Board):
        async with sem:
            try:
                return board, *(await ats.fetch_board(client, board)), None
            except (httpx.HTTPError, ValueError, KeyError) as e:
                return board, [], False, f"{type(e).__name__}: {e}"[:300]

    for done, task in enumerate(asyncio.as_completed([one(b) for b in boards]), 1):
        board, jobs, complete, error = await task
        store.mark_company(board, error)
        event = {"type": "board", "ats": board.ats, "board_id": board.board_id,
                 "done": done, "total": len(boards), "jobs": 0, "match": 0, "closed": 0, "error": error}
        if error:
            log.warning("board %s/%s failed: %s", board.ats, board.board_id, error)
            emit(event)
            continue
        live = {j.key for j in jobs}
        matching = [j for j in jobs if filters.keep(j)]
        for job in matching:
            store.upsert_job(job, ts)
        confirmed |= live
        closed = store.close_missing(board, live, ts) if complete else 0
        log.info("board %s/%s: %d jobs, %d match, %d closed",
                 board.ats, board.board_id, len(jobs), len(matching), closed)
        emit(event | {"jobs": len(jobs), "match": len(matching), "closed": closed})
    store.commit()
    return confirmed


async def check_liveness(
    store: Store, client: httpx.AsyncClient, confirmed: set[str], cfg: Config, playwright: bool,
    emit: Emit = _noop,
) -> dict[str, int]:
    """Phase 3: check every not-closed job a board API didn't just confirm."""
    rows = {r["key"]: r for r in store.jobs(("open", "unknown")) if r["key"] not in confirmed}
    progress = {"done": 0}

    def on_result(key: str, status: str):
        progress["done"] += 1
        r = rows[key]
        emit({"type": "check", "key": key, "title": r["title"], "company": r["company"],
              "status": status, "done": progress["done"], "total": len(rows)})

    results = await liveness.check_many(
        client, {k: r["url"] for k, r in rows.items()}, cfg.concurrency, playwright, on_result
    )
    ts = now()
    counts = {"open": 0, "closed": 0, "unknown": 0}
    for key, status in results.items():
        store.set_status(key, status, ts)
        counts[status] += 1
    store.commit()
    return counts


async def run_pipeline(
    cfg: Config, *, skip_exa: bool = False, playwright: bool = True,
    include_unknown: bool = False, emit: Emit = _noop,
) -> dict:
    """Run everything; returns a summary dict. Raises RuntimeError if Exa is needed but has no key."""
    started = time.monotonic()
    api_key = os.environ.get("EXA_API_KEY")
    if not skip_exa and not api_key:
        raise RuntimeError("EXA_API_KEY missing — put it in job_finder/.env, or run with Skip Exa")
    emit({"type": "run_start", "skip_exa": skip_exa, "at": now()})
    store = Store(cfg.path(cfg.db_path))
    summary: dict = {}
    try:
        filters = Filters(cfg)
        limits = httpx.Limits(max_connections=cfg.concurrency * 2)
        async with httpx.AsyncClient(timeout=30, headers={"User-Agent": UA}, limits=limits) as client:
            if skip_exa:
                emit({"type": "stage", "stage": "discover", "state": "skipped"})
            else:
                emit({"type": "stage", "stage": "discover", "state": "start"})
                hits = await exa_search.discover(
                    cfg, client, api_key, on_search=lambda e: emit({"type": "exa", **e})
                )
                kept = ingest_hits(store, filters, hits)
                summary |= {"exa_results": len(hits), "exa_kept": len(kept)}
                emit({"type": "stage", "stage": "discover", "state": "done",
                      "results": len(hits), "kept": len(kept)})

            emit({"type": "stage", "stage": "boards", "state": "start", "total": len(store.companies())})
            confirmed = await expand_boards(store, filters, client, cfg.concurrency, emit)
            summary |= {"boards": len(store.companies()), "board_jobs": len(confirmed)}
            emit({"type": "stage", "stage": "boards", "state": "done",
                  "boards": summary["boards"], "live": len(confirmed)})

            emit({"type": "stage", "stage": "liveness", "state": "start"})
            counts = await check_liveness(store, client, confirmed, cfg, playwright, emit)
            summary["liveness"] = counts
            emit({"type": "stage", "stage": "liveness", "state": "done", **counts})

        emit({"type": "stage", "stage": "export", "state": "start"})
        n, csv_path, json_path = export_jobs(store, cfg.path(cfg.out_dir), include_unknown)
        summary |= {"exported": n, "csv": str(csv_path), "json": str(json_path)}
        emit({"type": "stage", "stage": "export", "state": "done", "exported": n})
    finally:
        store.close()
    summary["seconds"] = round(time.monotonic() - started, 1)
    emit({"type": "run_done", **summary})
    return summary
