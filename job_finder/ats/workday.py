"""Workday via the site's own JSON endpoint: POST /wday/cxs/<tenant>/<site>/jobs.

Big tenants have thousands of jobs, so instead of pulling everything we run one search per
role (searchText) and merge. That makes the result partial, so missing jobs are never marked
closed from here — liveness.py checks Workday jobs individually.
"""

import logging

from ats import Board, make_key
from ats.common import mode_from_location
from models import Job

log = logging.getLogger(__name__)
PAGE = 20
MAX_PER_QUERY = 200


def split_id(board: Board) -> tuple[str, str, str]:
    tenant, wd, site = board.board_id.split("|")
    return tenant, wd, site


def parse(board: Board, payload: dict) -> list[Job]:
    tenant, wd, site = split_id(board)
    jobs = []
    for p in payload.get("jobPostings", []):
        path = p.get("externalPath")
        if not path:
            continue
        url = f"https://{tenant}.{wd}.myworkdayjobs.com/{site}{path}"
        location = p.get("locationsText", "")
        jobs.append(Job(
            key=make_key(board, path.rstrip("/").rsplit("/", 1)[-1]),
            url=url, apply_url=url,
            title=p.get("title", ""),
            company=tenant,
            location=location,
            work_mode=mode_from_location(f"{location} {p.get('remoteType', '')}"),
            posted_date="",  # Workday only gives "Posted 3 Days Ago"
            source="board", ats=board.ats, board_id=board.board_id, status="open",
        ))
    return jobs


async def fetch_board(client, board: Board, search_terms: list[str] | None = None):
    tenant, wd, site = split_id(board)
    endpoint = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    terms = search_terms or ["SDET", "QA Automation", "Test Automation", "AI Engineer", "AI Automation"]
    found: dict[str, Job] = {}
    for term in terms:
        for offset in range(0, MAX_PER_QUERY, PAGE):
            r = await client.post(
                endpoint,
                json={"appliedFacets": {}, "limit": PAGE, "offset": offset, "searchText": term},
                headers={"Accept": "application/json"},
            )
            r.raise_for_status()
            data = r.json()
            batch = parse(board, data)
            for job in batch:
                found.setdefault(job.key, job)
            if len(batch) < PAGE or offset + PAGE >= data.get("total", 0):
                break
    return list(found.values()), False
