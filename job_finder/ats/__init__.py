"""ATS detection from URLs, stable job keys, and dispatch to each ATS's board fetcher.

A Board is (ats, board_id). Workday board ids are "tenant|wdN|site".
"""

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

_TRACKING = re.compile(r"^(utm_|gh_src$|source$|src$|ref$|lever-|referrer$|error$)", re.I)
_WORKDAY_HOST = re.compile(r"^([\w-]+)\.(wd\d+)\.myworkdayjobs\.com$")
_LOCALE = re.compile(r"^[a-z]{2}(-[A-Za-z]{2})?$")
_GREENHOUSE_HOSTS = {
    "boards.greenhouse.io", "job-boards.greenhouse.io",
    "boards.eu.greenhouse.io", "job-boards.eu.greenhouse.io",
}
_LEVER_HOSTS = {"jobs.lever.co", "jobs.eu.lever.co"}
_SR_HOSTS = {"jobs.smartrecruiters.com", "careers.smartrecruiters.com"}


@dataclass(frozen=True)
class Board:
    ats: str
    board_id: str


def canonical_url(url: str) -> str:
    """https, lowercase host without www, no tracking params or fragment, no trailing slash."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    query = sorted((k, v) for k, v in parse_qsl(parts.query) if not _TRACKING.match(k))
    path = parts.path.rstrip("/")
    if host in _LEVER_HOSTS:
        path = re.sub(r"/apply$", "", path)
    return urlunsplit(("https", host, path, urlencode(query), ""))


def _segments(path: str) -> list[str]:
    return [unquote(s) for s in path.split("/") if s]


def detect_board(url: str) -> Board | None:
    parts = urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.")
    segs = _segments(parts.path)
    if host in _GREENHOUSE_HOSTS:
        if segs and segs[0] == "embed":
            token = dict(parse_qsl(parts.query)).get("for")
            return Board("greenhouse", token.lower()) if token else None
        return Board("greenhouse", segs[0].lower()) if segs else None
    if host in _LEVER_HOSTS:
        return Board("lever", segs[0].lower()) if segs else None
    if host == "jobs.ashbyhq.com":
        return Board("ashby", segs[0]) if segs else None
    if host in _SR_HOSTS:
        return Board("smartrecruiters", segs[0]) if segs else None
    if m := _WORKDAY_HOST.match(host):
        site_segs = [s for s in segs if not _LOCALE.match(s)]
        if site_segs and site_segs[0] not in ("wday", "job"):
            return Board("workday", f"{m.group(1)}|{m.group(2)}|{site_segs[0]}")
    return None


def job_id_from_url(board: Board, url: str) -> str | None:
    parts = urlsplit(url)
    segs = _segments(parts.path)
    query = dict(parse_qsl(parts.query))
    if board.ats == "greenhouse":
        if "token" in query:  # embed/job_app?for=x&token=123
            return query["token"]
        if "gh_jid" in query:
            return query["gh_jid"]
        if "jobs" in segs and segs.index("jobs") + 1 < len(segs):
            return segs[segs.index("jobs") + 1]
    elif board.ats in ("lever", "ashby"):
        return segs[1] if len(segs) > 1 else None
    elif board.ats == "smartrecruiters":
        if len(segs) > 1 and (m := re.match(r"(\d+)", segs[1])):
            return m.group(1)
    elif board.ats == "workday":
        if "job" in segs and len(segs) > segs.index("job") + 1:
            return segs[-1]
    return None


def make_key(board: Board, job_id: str) -> str:
    return f"{board.ats}:{board.board_id.lower()}:{job_id.lower()}"


def job_key(url: str) -> tuple[str, Board | None]:
    """Stable key for a job URL plus its board (if it is on a known ATS)."""
    board = detect_board(url)
    if board and (jid := job_id_from_url(board, url)):
        return make_key(board, jid), board
    return "url:" + canonical_url(url), board


async def fetch_board(client, board: Board):
    """Return (jobs, complete). complete=False means the list may be partial (don't close missing)."""
    from ats import ashby, greenhouse, lever, smartrecruiters, workday

    module = {
        "greenhouse": greenhouse, "lever": lever, "ashby": ashby,
        "smartrecruiters": smartrecruiters, "workday": workday,
    }[board.ats]
    return await module.fetch_board(client, board)
