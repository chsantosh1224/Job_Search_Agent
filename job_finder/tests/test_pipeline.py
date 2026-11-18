import asyncio

import httpx

import pipeline
from ats import Board
from exa_search import Hit, JobSummary
from export import export
from filters import Filters
from models import Job
from store import Store


def test_upsert_merges_and_board_wins():
    s = Store(":memory:")
    s.upsert_job(Job(key="k", url="u1", title="SDET", location="", source="exa:A"))
    s.upsert_job(Job(key="k", url="u2", title="SDET II", location="Bengaluru", source="board", status="open"))
    s.upsert_job(Job(key="k", url="u3", title="Old title", source="exa:B"))
    row = s.jobs()[0]
    assert (row["url"], row["title"], row["location"], row["source"], row["status"]) == \
        ("u2", "SDET II", "Bengaluru", "board", "open")


def test_close_missing():
    s = Store(":memory:")
    for k in ("lever:acme:1", "lever:acme:2"):
        s.upsert_job(Job(key=k, url=k, title="SDET", ats="lever", board_id="acme", status="open"))
    assert s.close_missing(Board("lever", "acme"), {"lever:acme:1"}) == 1
    assert {r["key"]: r["status"] for r in s.jobs()} == {"lever:acme:1": "open", "lever:acme:2": "closed"}


def test_end_to_end_without_exa(cfg, tmp_path):
    """Exa hit registers a board; board expansion confirms it; a non-ATS job gets liveness-checked."""
    s = Store(":memory:")
    f = Filters(cfg)
    hits = [
        Hit(url="https://jobs.lever.co/acme/U1", title="", run="A", query="q", summary=JobSummary(
            is_job_posting=True, is_open=True, job_title="SDET", company="Acme", location="Bengaluru")),
        Hit(url="https://careers.beta.com/jobs/77", title="", run="B", query="q", summary=JobSummary(
            is_job_posting=True, is_open=True, job_title="AI Engineer", company="Beta",
            location="Remote, India", work_mode="remote")),
        Hit(url="https://careers.gamma.com/jobs/88", title="", run="B", query="q", summary=JobSummary(
            is_job_posting=True, is_open=True, job_title="Sales Lead", company="Gamma", location="Bengaluru")),
    ]
    assert len(pipeline.ingest_hits(s, f, hits)) == 2
    assert s.companies() == [Board("lever", "acme")]

    body = "<p>" + "Build LLM agents. " * 40 + "</p>"

    def handler(req):
        if req.url.host == "api.lever.co":
            return httpx.Response(200, json=[
                {"id": "U1", "text": "SDET", "hostedUrl": "https://jobs.lever.co/acme/U1",
                 "categories": {"location": "Bengaluru"}},
                {"id": "U2", "text": "QA Automation Engineer", "hostedUrl": "https://jobs.lever.co/acme/U2",
                 "categories": {"location": "Bangalore"}},
                {"id": "U3", "text": "Account Executive", "hostedUrl": "https://jobs.lever.co/acme/U3",
                 "categories": {"location": "Bengaluru"}}])
        return httpx.Response(200, text=body)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            confirmed = await pipeline.expand_boards(s, f, c, 5)
            counts = await pipeline.check_liveness(s, c, confirmed, cfg, playwright=False)
            return confirmed, counts

    confirmed, counts = asyncio.run(go())
    assert "lever:acme:u1" in confirmed and counts == {"open": 1, "closed": 0, "unknown": 0}
    n, csv_path, _ = export(s, tmp_path)
    assert n == 3
    assert "QA Automation Engineer" in csv_path.read_text(encoding="utf-8")
