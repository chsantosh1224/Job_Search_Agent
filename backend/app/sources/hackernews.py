"""Monthly "Ask HN: Who is hiring?" thread, via the official HN Algolia API.

Each top-level comment is one company's post. By convention the first line is a header like
"Company | Role(s) | Location | REMOTE | Salary"; the rest is free text.
"""

import html
import re
from collections.abc import Iterator
from datetime import datetime

from app.normalize.salary import parse_salary
from app.normalize.text import html_to_text
from app.sources.base import FetchContext, RawJob, find_ats_links

SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
ITEM_URL = "https://hn.algolia.com/api/v1/items/{}"

_SEPARATOR = re.compile(r"\s+[|•·—–]\s+|\s*\|\s*")
# Header parts about where the work happens, including hiring time-zone bands.
_WORK_MODE = re.compile(
    r"\b(remote|on-?site|hybrid|in[- ]office|in[- ]person|wfh|gmt|utc)\b", re.IGNORECASE
)
_ROLE_WORDS = re.compile(r"\b(engineer|developer|scientist|sdet|architect|lead)s?\b", re.IGNORECASE)


def parse_header(header: str) -> tuple[str, str, str]:
    """Split a post header into (company, title, location)."""
    header = header.strip().split("\n", 1)[0]
    parts = [p.strip() for p in _SEPARATOR.split(header) if p.strip()]
    # Drop "(Remote US)"-style notes, including ones cut open by a "|" inside the parentheses.
    company = re.sub(r"\s*\(.*$", "", parts[0]) if parts else "Unknown"
    if len(parts) <= 1 or len(company) > 60:
        # Prose instead of a "A | B | C" header: take the leading name-like words.
        company = " ".join(re.split(r"\s+[-–—:,]\s*|[:,]", company, maxsplit=1)[0].split()[:5])
    roles = [p for p in parts[1:] if _ROLE_WORDS.search(p)]
    title = ", ".join(roles) if roles else header[:200]
    # Work-mode parts, plus "(Remote US)"-style notes attached to the company name.
    location_parts = [p for p in parts if _WORK_MODE.search(p)]
    return company[:255], title[:500], " / ".join(location_parts)


def parse_thread(item: dict) -> Iterator[RawJob]:
    for comment in item.get("children", []):
        raw_html = comment.get("text")
        if not raw_html:  # deleted or flagged
            continue
        header_html = re.split(r"<p>", raw_html, maxsplit=1)[0]
        header = html_to_text(header_html)
        company, title, location = parse_header(header)
        description = html_to_text(raw_html)
        yield RawJob(
            source="hackernews",
            source_job_id=str(comment["id"]),
            url=f"https://news.ycombinator.com/item?id={comment['id']}",
            title=title,
            company_name=company,
            description=description,
            location=location or None,
            strict_location=False,
            salary=parse_salary(header) or parse_salary(description),
            posted_at=datetime.fromisoformat(comment["created_at"]),
            extra={"header": header, "thread_id": item.get("id")},
            ats_links=find_ats_links(html.unescape(raw_html)),
        )


class HackerNews:
    name = "hackernews"

    def fetch(self, ctx: FetchContext) -> Iterator[RawJob]:
        hits = ctx.http.json(
            SEARCH_URL, tags="story,author_whoishiring", query="who is hiring", hitsPerPage=5
        )["hits"]
        thread = next(h for h in hits if h["title"].startswith("Ask HN: Who is hiring?"))
        yield from parse_thread(ctx.http.json(ITEM_URL.format(thread["objectID"])))
