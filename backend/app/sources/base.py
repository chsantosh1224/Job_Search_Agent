import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.normalize.salary import Salary
from app.sources.http import HttpClient


@dataclass
class RawJob:
    """A job as one source describes it, before storage and filtering."""

    source: str
    source_job_id: str
    url: str
    title: str
    company_name: str
    description: str = ""
    location: str | None = None  # places only, where the source separates them
    workplace: str | None = None  # explicit "remote" / "hybrid" / "onsite", when a source has one
    strict_location: bool = True  # False for free-text locations (HN headers)
    salary: Salary | None = None
    posted_at: datetime | None = None
    company_website: str | None = None
    company_description: str | None = None
    yc_batch: str | None = None
    extra: dict = field(default_factory=dict)
    # Greenhouse / Lever / Ashby boards mentioned in the post, for company discovery.
    ats_links: set[tuple[str, str]] = field(default_factory=set)


@dataclass
class FetchContext:
    http: HttpClient
    # Company boards to read: (ats_type, slug, company name).
    ats_boards: list[tuple[str, str, str]] = field(default_factory=list)
    # source_job_ids already stored, so connectors can skip expensive detail fetches.
    known_ids: set[str] = field(default_factory=set)


class Source(Protocol):
    name: str

    def fetch(self, ctx: FetchContext) -> Iterator[RawJob]: ...


_ATS_LINK_RE = re.compile(
    r"(?:(?:job-)?boards(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?(?P<gh>[A-Za-z0-9_-]+)"
    r"|jobs(?:\.eu)?\.lever\.co/(?P<lever>[A-Za-z0-9_.-]+)"
    r"|jobs\.ashbyhq\.com/(?P<ashby>[A-Za-z0-9_.%-]+))"
)
_NOT_SLUGS = {"embed", "api", "v1", "jobs"}


def find_ats_links(text: str) -> set[tuple[str, str]]:
    links = set()
    for match in _ATS_LINK_RE.finditer(text):
        for ats_type, key in (("greenhouse", "gh"), ("lever", "lever"), ("ashby", "ashby")):
            slug = match.group(key)
            if slug and slug.lower() not in _NOT_SLUGS:
                links.add((ats_type, slug.rstrip(".")))
    return links
