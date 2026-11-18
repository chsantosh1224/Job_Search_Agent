"""Phase 1: Exa discovery.

Calls the Exa REST /search endpoint directly with httpx (camelCase field names from
https://exa.ai/docs/reference/search). Per-result structured fields come from
contents.summary.schema — the top-level outputSchema returns ONE synthesized answer for the
whole query, not one object per result, so it does not fit "classify each page".
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

from settings import Config

log = logging.getLogger(__name__)
EXA_URL = "https://api.exa.ai/search"

HIGHLIGHTS_QUERY = (
    "job title, location, remote or onsite, years of experience, key skills, posted date, "
    "whether the job is still open"
)
SUMMARY_QUERY = (
    "Extract the job posting on this page. is_open is false if the page says the job is closed, "
    "filled, expired or no longer accepting applications. posted_by_agency is true if a staffing "
    "or recruitment agency posted it on behalf of an unnamed or different client company."
)
SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "is_job_posting": {"type": "boolean", "description": "Page is a single job posting"},
        "is_open": {"type": "boolean"},
        "job_title": {"type": "string"},
        "company": {"type": "string", "description": "Hiring company (not the agency)"},
        "location": {"type": "string"},
        "work_mode": {"type": "string", "enum": ["onsite", "hybrid", "remote", "unknown"]},
        "experience_required": {"type": "string"},
        "posted_date": {"type": "string", "description": "YYYY-MM-DD if stated"},
        "apply_url": {"type": "string"},
        "posted_by_agency": {"type": "boolean"},
    },
    "required": ["is_job_posting", "is_open", "job_title", "company", "posted_by_agency"],
}


class JobSummary(BaseModel):
    is_job_posting: bool = False
    is_open: bool = False
    job_title: str = ""
    company: str = ""
    location: str = ""
    work_mode: Literal["onsite", "hybrid", "remote", "unknown"] = "unknown"
    experience_required: str = ""
    posted_date: str = ""
    apply_url: str = ""
    posted_by_agency: bool = False


@dataclass
class Hit:
    url: str
    title: str
    run: str
    query: str
    published_date: str = ""
    highlights: list[str] = field(default_factory=list)
    summary: JobSummary | None = None

    @property
    def is_candidate(self) -> bool:
        s = self.summary
        return bool(s and s.is_job_posting and s.is_open and not s.posted_by_agency)


def build_payload(cfg: Config, query: str, run: str, today: date) -> dict | None:
    """Run A = ATS domains only, B = everything but aggregators, C = target company domains.
    A and C are skipped (None) when their domain list is empty."""
    payload: dict = {
        "query": query,
        "type": cfg.search_type,
        "numResults": cfg.num_results,
        "userLocation": cfg.user_location,
        "startPublishedDate": (today - timedelta(days=cfg.published_within_days)).isoformat()
        + "T00:00:00.000Z",
        "contents": {
            "highlights": {"query": HIGHLIGHTS_QUERY, "maxCharacters": cfg.highlights_max_chars},
            "summary": {"query": SUMMARY_QUERY, "schema": SUMMARY_SCHEMA},
            "livecrawlTimeout": cfg.livecrawl_timeout_ms,
        },
    }
    if cfg.max_age_hours is not None:
        payload["contents"]["maxAgeHours"] = cfg.max_age_hours
    if run == "A":
        if not cfg.ats_domains:
            return None
        payload["includeDomains"] = cfg.ats_domains
    elif run == "B":
        payload["excludeDomains"] = cfg.exclude_domains
    elif run == "C":
        if not cfg.target_company_domains:
            return None
        payload["includeDomains"] = cfg.target_company_domains
    else:
        raise ValueError(run)
    return payload


def parse_summary(raw: object) -> JobSummary | None:
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str) and raw.strip():
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
    else:
        return None
    try:
        return JobSummary.model_validate(
            {k: v for k, v in data.items() if v is not None and k in JobSummary.model_fields}
        )
    except ValidationError:
        data["work_mode"] = "unknown"
        try:
            return JobSummary.model_validate(data)
        except ValidationError:
            return None


def parse_summary_date(value: str) -> str:
    m = re.search(r"\d{4}-\d{2}-\d{2}", value or "")
    return m.group(0) if m else ""


def parse_response(resp: dict, run: str, query: str) -> list[Hit]:
    hits = []
    for r in resp.get("results", []):
        if not r.get("url"):
            continue
        hits.append(Hit(
            url=r["url"],
            title=r.get("title") or "",
            run=run,
            query=query,
            published_date=(r.get("publishedDate") or "")[:10],
            highlights=r.get("highlights") or [],
            summary=parse_summary(r.get("summary")),
        ))
    return hits


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


async def search(client: httpx.AsyncClient, api_key: str, payload: dict) -> dict:
    r = await client.post(EXA_URL, json=payload, headers={"x-api-key": api_key}, timeout=300)
    r.raise_for_status()
    return r.json()


async def discover(
    cfg: Config, client: httpx.AsyncClient, api_key: str, today: date | None = None,
    on_search=None,
) -> list[Hit]:
    """on_search(event: dict) is called before and after every Exa request (for progress UIs)."""
    today = today or date.today()
    raw_dir: Path = cfg.path(cfg.raw_dir) / today.isoformat()
    raw_dir.mkdir(parents=True, exist_ok=True)
    plan = [(q, r, p) for q in cfg.queries for r in ("A", "B", "C")
            if (p := build_payload(cfg, q, r, today)) is not None]
    notify = on_search or (lambda e: None)
    hits: list[Hit] = []
    for i, (query, run, payload) in enumerate(plan):
        notify({"state": "start", "run": run, "query": query, "index": i, "total": len(plan)})
        try:
            resp = await search(client, api_key, payload)
        except httpx.HTTPError as e:
            body = getattr(getattr(e, "response", None), "text", "")[:300]
            log.error("Exa run %s failed for %r: %s %s", run, query, e, body)
            notify({"state": "error", "run": run, "query": query, "index": i, "total": len(plan),
                    "error": f"{e} {body}".strip()[:300]})
            continue
        (raw_dir / f"{run}_{_slug(query)}.json").write_text(
            json.dumps({"request": payload, "response": resp}, indent=1), encoding="utf-8"
        )
        batch = parse_response(resp, run, query)
        candidates = sum(h.is_candidate for h in batch)
        log.info("Exa run %s %r: %d results, %d open postings", run, query, len(batch), candidates)
        notify({"state": "done", "run": run, "query": query, "index": i, "total": len(plan),
                "results": len(batch), "candidates": candidates})
        hits += batch
    return hits
