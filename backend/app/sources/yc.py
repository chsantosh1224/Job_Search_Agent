"""YC job board (ycombinator.com/jobs). robots.txt allows /jobs and /companies/*/jobs.

Listing pages embed their data as JSON in a `data-page` attribute. Detail pages add the full
description, company website, founders and hiring manager, which research briefs use. Detail
pages are only fetched for new jobs whose title is in a target role family.
"""

import html
import json
import re
from collections.abc import Callable, Iterator

from app.normalize.salary import parse_salary
from app.normalize.text import html_to_text
from app.sources.base import FetchContext, RawJob, find_ats_links

BASE_URL = "https://www.ycombinator.com"
LISTING_PATHS = [
    "/jobs/role/software-engineer/remote",
    "/jobs/role/software-engineer/india",
    "/jobs/role/science/remote",
]
_DATA_PAGE = re.compile(r'data-page="([^"]+)"')


def page_props(page_html: str) -> dict:
    match = _DATA_PAGE.search(page_html)
    if not match:
        raise ValueError("YC page has no data-page payload; the page format may have changed")
    return json.loads(html.unescape(match.group(1)))["props"]


def _people(founders: list[dict] | None) -> list[dict]:
    return [
        {"name": f.get("full_name"), "title": f.get("title"), "linkedin": f.get("linkedin_url")}
        for f in founders or []
        if f.get("full_name")
    ]


def split_location(location: str | None) -> tuple[str | None, str]:
    """'SF, CA, US / Remote (US)' -> ('Remote (US)', 'remote').

    YC lists office cities and the remote scope as separate '/' segments; the offices say
    nothing about where a remote hire may live.
    """
    segments = [s.strip() for s in (location or "").split(" / ") if s.strip()]
    remote = [s for s in segments if s.lower().startswith("remote")]
    if remote:
        return " / ".join(remote), "remote"
    return location, "onsite"


def build_job(posting: dict, detail: dict | None) -> RawJob:
    job = (detail or {}).get("job") or posting
    company = (detail or {}).get("company") or {}
    manager = job.get("hiringManager") or {}
    description_md = job.get("description") or ""
    visa = job.get("visa")
    location, workplace = split_location(posting.get("location"))
    return RawJob(
        source="yc",
        source_job_id=str(posting["id"]),
        url=BASE_URL + posting["url"],
        title=posting["title"].strip(),
        company_name=posting["companyName"].strip(),
        # Visa line goes into the text the location classifier reads.
        description="\n\n".join(filter(None, [html_to_text(description_md),
                                               f"Visa: {visa}" if visa else None])),
        location=location,
        workplace=workplace,
        salary=parse_salary(posting.get("salaryRange")),
        company_website=company.get("website"),
        company_description=company.get("long_description") or posting.get("companyOneLiner"),
        yc_batch=posting.get("companyBatchName"),
        extra={
            "listed_location": posting.get("location"),
            "one_liner": posting.get("companyOneLiner"),
            "visa": visa,
            "min_experience": posting.get("minExperience"),
            "equity": posting.get("equityRange") or None,
            "role_type": posting.get("roleSpecificType"),
            "team_size": company.get("team_size"),
            "founders": _people(company.get("founders")),
            "hiring_manager": " ".join(
                filter(None, [manager.get("first_name"), manager.get("last_name")])
            ) or None,
            "last_active": posting.get("lastActive"),
        },
        ats_links=find_ats_links(description_md),
    )


class YCJobs:
    name = "yc"

    def __init__(self, title_filter: Callable[[str], bool]):
        self._wanted = title_filter

    def fetch(self, ctx: FetchContext) -> Iterator[RawJob]:
        seen: set[str] = set()
        for path in LISTING_PATHS:
            for posting in page_props(ctx.http.text(BASE_URL + path))["jobPostings"]:
                job_id = str(posting["id"])
                if job_id in seen:
                    continue
                seen.add(job_id)
                detail = None
                if job_id not in ctx.known_ids and self._wanted(posting["title"]):
                    detail = page_props(ctx.http.text(BASE_URL + posting["url"]))
                yield build_job(posting, detail)
