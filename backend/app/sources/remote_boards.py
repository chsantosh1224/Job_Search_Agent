"""RemoteOK and Remotive public APIs.

Both require attribution: jobs keep their board URL, and the dashboard shows the source.
Remotive asks for no more than a few requests a day; one daily run is well within that.
"""

from collections.abc import Iterator
from datetime import UTC, datetime

from app.normalize.salary import from_range, parse_salary
from app.normalize.text import html_to_text
from app.sources.base import FetchContext, RawJob, find_ats_links


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_remoteok(items: list[dict]) -> Iterator[RawJob]:
    for item in items:
        if "id" not in item or "position" not in item:  # first element is the legal notice
            continue
        description_html = item.get("description") or ""
        low, high = item.get("salary_min") or None, item.get("salary_max") or None
        salary = from_range(f"${low or high}-{high or low}", low, high, "USD") if (low or high) else None
        yield RawJob(
            source="remoteok",
            source_job_id=str(item["id"]),
            url=item.get("url") or f"https://remoteok.com/remote-jobs/{item['id']}",
            title=item["position"].strip(),
            company_name=(item.get("company") or "").strip(),
            description=html_to_text(description_html),
            location=item.get("location") or None,
            workplace="remote",
            salary=salary,
            posted_at=_parse_datetime(item.get("date")),
            extra={"tags": item.get("tags") or []},
            ats_links=find_ats_links(description_html + " " + (item.get("apply_url") or "")),
        )


class RemoteOK:
    name = "remoteok"

    def fetch(self, ctx: FetchContext) -> Iterator[RawJob]:
        yield from parse_remoteok(ctx.http.json("https://remoteok.com/api"))


def parse_remotive(payload: dict) -> Iterator[RawJob]:
    for item in payload.get("jobs", []):
        description_html = item.get("description") or ""
        yield RawJob(
            source="remotive",
            source_job_id=str(item["id"]),
            url=item["url"],
            title=item["title"].strip(),
            company_name=(item.get("company_name") or "").strip(),
            description=html_to_text(description_html),
            location=item.get("candidate_required_location") or None,
            workplace="remote",
            # Remotive writes bare "70K-80K"; its salaries are USD unless marked otherwise.
            salary=parse_salary(item.get("salary"), default_currency="USD"),
            posted_at=_parse_datetime(item.get("publication_date")),
            extra={"job_type": item.get("job_type"), "tags": item.get("tags") or [],
                   "category": item.get("category")},
            ats_links=find_ats_links(description_html),
        )


class Remotive:
    name = "remotive"

    def fetch(self, ctx: FetchContext) -> Iterator[RawJob]:
        yield from parse_remotive(ctx.http.json("https://remotive.com/api/remote-jobs"))
