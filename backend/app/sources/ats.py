"""Company job boards on Greenhouse, Lever and Ashby, via their public job-board APIs.

Which companies to read comes from the companies table: boards discovered in other sources'
posts, plus any added by hand in config/ats_companies.txt.
"""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx

from app.normalize.salary import from_range, parse_salary
from app.normalize.text import html_to_text
from app.sources.base import FetchContext, RawJob

log = logging.getLogger(__name__)

_LEVER_INTERVALS = {"per-hour-wage": "hour", "per-month-salary": "month"}


def workplace_type(value: object) -> str | None:
    """Map each ATS's workplace label (Remote / Hybrid / OnSite / on-site / In Office) to ours."""
    if not isinstance(value, str):
        return None
    value = value.lower().replace("-", "").replace(" ", "")
    if value == "remote":
        return "remote"
    if value == "hybrid":
        return "hybrid"
    if value in ("onsite", "inoffice", "inperson", "office"):
        return "onsite"
    return None


def parse_greenhouse(slug: str, company: str, payload: dict) -> Iterator[RawJob]:
    for job in payload.get("jobs", []):
        description = html_to_text(job.get("content"))
        location_type = next(
            (m.get("value") for m in job.get("metadata") or []
             if (m.get("name") or "").lower() in ("location type", "workplace type")),
            None,
        )
        yield RawJob(
            source="greenhouse",
            source_job_id=f"{slug}:{job['id']}",
            url=job["absolute_url"],
            title=job["title"].strip(),
            company_name=job.get("company_name") or company,
            description=description,
            location=(job.get("location") or {}).get("name"),
            workplace=workplace_type(location_type),
            salary=parse_salary(description),
            posted_at=_iso(job.get("first_published") or job.get("updated_at")),
        )


def parse_lever(slug: str, company: str, postings: list[dict]) -> Iterator[RawJob]:
    for job in postings:
        categories = job.get("categories") or {}
        description = "\n\n".join(filter(None, [
            job.get("descriptionPlain"),
            *(f"{section.get('text')}\n{html_to_text(section.get('content'))}"
              for section in job.get("lists") or []),
            job.get("additionalPlain"),
        ]))
        salary_range = job.get("salaryRange") or {}
        interval = _LEVER_INTERVALS.get(salary_range.get("interval"), "year")
        salary = from_range(
            f"{salary_range.get('min')}-{salary_range.get('max')} "
            f"{salary_range.get('currency')} per {interval}",
            salary_range.get("min"), salary_range.get("max"), salary_range.get("currency"),
            interval,
        ) if salary_range else parse_salary(description)
        yield RawJob(
            source="lever",
            source_job_id=f"{slug}:{job['id']}",
            url=job["hostedUrl"],
            title=job["text"].strip(),
            company_name=company,
            description=description,
            location=" / ".join(categories.get("allLocations") or [])
            or categories.get("location"),
            workplace=workplace_type(job.get("workplaceType")),
            salary=salary,
            posted_at=datetime.fromtimestamp(job["createdAt"] / 1000, tz=UTC)
            if job.get("createdAt") else None,
            extra={"commitment": categories.get("commitment")},
        )


def parse_ashby(slug: str, company: str, payload: dict) -> Iterator[RawJob]:
    for job in payload.get("jobs", []):
        if job.get("isListed") is False:
            continue
        locations = [job.get("location")] + [
            loc.get("location") for loc in job.get("secondaryLocations") or []
        ]
        workplace = workplace_type(job.get("workplaceType"))
        if workplace is None and job.get("isRemote"):
            workplace = "remote"
        compensation = job.get("compensation") or {}
        yield RawJob(
            source="ashby",
            source_job_id=f"{slug}:{job['id']}",
            url=job["jobUrl"],
            title=job["title"].strip(),
            company_name=company,
            description=job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml")),
            location=" / ".join(filter(None, locations)),
            workplace=workplace,
            salary=parse_salary(compensation.get("scrapeableCompensationSalarySummary")
                                or compensation.get("compensationTierSummary")),
            posted_at=_iso(job.get("publishedAt")),
            extra={"employment_type": job.get("employmentType")},
        )


def _iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class CompanyBoards:
    name = "ats"

    def fetch(self, ctx: FetchContext) -> Iterator[RawJob]:
        for ats_type, slug, company in ctx.ats_boards:
            try:
                if ats_type == "greenhouse":
                    payload = ctx.http.json(
                        f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", content="true"
                    )
                    yield from parse_greenhouse(slug, company, payload)
                elif ats_type == "lever":
                    payload = ctx.http.json(f"https://api.lever.co/v0/postings/{slug}", mode="json")
                    yield from parse_lever(slug, company, payload)
                elif ats_type == "ashby":
                    payload = ctx.http.json(
                        f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
                        includeCompensation="true",
                    )
                    yield from parse_ashby(slug, company, payload)
            except httpx.HTTPStatusError as exc:
                # Boards get renamed or closed; one bad slug must not stop the others.
                log.warning("Skipping %s board %r: %s", ats_type, slug, exc)
