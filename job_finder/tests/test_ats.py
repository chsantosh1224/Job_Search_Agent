import asyncio

import httpx
import pytest

import ats
from ats import Board, canonical_url, detect_board, job_key


@pytest.mark.parametrize("url,board", [
    ("https://boards.greenhouse.io/Acme/jobs/123", Board("greenhouse", "acme")),
    ("https://job-boards.greenhouse.io/acme/jobs/123?gh_src=x", Board("greenhouse", "acme")),
    ("https://boards.greenhouse.io/embed/job_app?for=acme&token=123", Board("greenhouse", "acme")),
    ("https://jobs.lever.co/acme/0f1e-uuid/apply", Board("lever", "acme")),
    ("https://jobs.ashbyhq.com/Acme/abc-uuid", Board("ashby", "Acme")),
    ("https://jobs.smartrecruiters.com/AcmeInc/744000-sdet", Board("smartrecruiters", "AcmeInc")),
    ("https://acme.wd5.myworkdayjobs.com/en-US/External/job/Bangalore/SDET_R1",
     Board("workday", "acme|wd5|External")),
    ("https://www.linkedin.com/jobs/view/1", None),
])
def test_detect_board(url, board):
    assert detect_board(url) == board


def test_keys_match_across_url_variants():
    a, _ = job_key("https://boards.greenhouse.io/acme/jobs/123")
    b, _ = job_key("https://job-boards.greenhouse.io/Acme/jobs/123?utm_source=x")
    c, _ = job_key("https://boards.greenhouse.io/embed/job_app?for=acme&token=123")
    assert a == b == c == "greenhouse:acme:123"
    assert job_key("https://jobs.lever.co/acme/UUID/apply")[0] == "lever:acme:uuid"
    assert job_key("https://acme.wd5.myworkdayjobs.com/en-US/External/job/Bangalore/SDET_R1")[0] \
        == "workday:acme|wd5|external:sdet_r1"
    assert job_key("https://careers.acme.com/jobs/9?utm_medium=x")[0] == "url:https://careers.acme.com/jobs/9"


def test_canonical_url():
    assert canonical_url("http://www.Acme.com/jobs/1/?utm_source=a&id=2#top") == "https://acme.com/jobs/1?id=2"


def _fetch(board, routes):
    def handler(request: httpx.Request):
        for prefix, payload in routes.items():
            if str(request.url).startswith(prefix):
                return httpx.Response(200, json=payload)
        return httpx.Response(404)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await ats.fetch_board(c, board)
    return asyncio.run(go())


def test_greenhouse():
    jobs, complete = _fetch(Board("greenhouse", "acme"), {"https://boards-api.greenhouse.io/v1/boards/acme/jobs": {
        "jobs": [{"id": 123, "title": "SDET II", "absolute_url": "https://acme.com/careers?gh_jid=123",
                  "location": {"name": "Bengaluru, India"}, "updated_at": "2026-11-10T00:00:00Z",
                  "company_name": "Acme"}]}})
    assert complete and jobs[0].key == "greenhouse:acme:123"
    assert jobs[0].company == "Acme" and jobs[0].posted_date == "2026-11-10"


def test_lever():
    jobs, _ = _fetch(Board("lever", "acme"), {"https://api.lever.co/v0/postings/acme": [
        {"id": "U1", "text": "QA Automation Engineer", "hostedUrl": "https://jobs.lever.co/acme/U1",
         "categories": {"location": "Remote - India"}, "workplaceType": "remote", "createdAt": 1763000000000}]})
    assert jobs[0].key == "lever:acme:u1" and jobs[0].work_mode == "remote"


def test_ashby_skips_unlisted():
    jobs, _ = _fetch(Board("ashby", "Acme"), {"https://api.ashbyhq.com/posting-api/job-board/Acme": {"jobs": [
        {"id": "a1", "title": "AI Engineer", "jobUrl": "https://jobs.ashbyhq.com/Acme/a1", "location": "Bengaluru",
         "isRemote": False, "publishedAt": "2026-11-01T00:00:00Z"},
        {"id": "a2", "title": "Hidden", "jobUrl": "x", "isListed": False}]}})
    assert [j.key for j in jobs] == ["ashby:acme:a1"]


def test_smartrecruiters():
    jobs, complete = _fetch(Board("smartrecruiters", "AcmeInc"), {
        "https://api.smartrecruiters.com/v1/companies/AcmeInc/postings": {"totalFound": 1, "content": [
            {"id": "744", "name": "SDET", "location": {"city": "Bengaluru", "country": "in", "remote": False},
             "releasedDate": "2026-11-12T00:00:00.000Z", "company": {"name": "Acme Inc"}}]}})
    assert complete and jobs[0].url == "https://jobs.smartrecruiters.com/AcmeInc/744"
    assert jobs[0].company == "Acme Inc"


def test_workday_is_partial():
    jobs, complete = _fetch(Board("workday", "acme|wd5|External"), {
        "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/External/jobs": {"total": 1, "jobPostings": [
            {"title": "SDET", "externalPath": "/job/Bangalore/SDET_R1", "locationsText": "Bangalore"}]}})
    assert not complete and jobs[0].key == "workday:acme|wd5|external:sdet_r1"
