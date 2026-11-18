import asyncio

import httpx
import pytest

from liveness import check_many, classify

BODY = "<html><body>" + "We are hiring an SDET to build test frameworks. " * 20 + "</body></html>"


@pytest.mark.parametrize("orig,status,final,html,expected", [
    ("https://a.com/jobs/123", 200, "https://a.com/jobs/123", BODY, "open"),
    ("https://a.com/jobs/123", 404, "https://a.com/jobs/123", "", "closed"),
    ("https://a.com/jobs/123", 410, "https://a.com/jobs/123", "", "closed"),
    ("https://boards.greenhouse.io/a/jobs/123", 200, "https://job-boards.greenhouse.io/a?error=true", BODY, "closed"),
    ("https://a.com/jobs/123", 200, "https://a.com/careers", BODY, "closed"),
    ("https://boards.greenhouse.io/a/jobs/123", 200, "https://job-boards.greenhouse.io/a/jobs/123", BODY, "open"),
    ("https://a.com/jobs/123", 200, "https://a.com/jobs/123", BODY + "This position has been filled.", "closed"),
    ("https://a.com/jobs/123", 403, "https://a.com/jobs/123", "", "unknown"),
    ("https://a.com/jobs/123", 200, "https://a.com/jobs/123", "<div id=root></div>", "unknown"),
])
def test_classify(orig, status, final, html, expected):
    assert classify(orig, status, final, html) == expected


def test_check_many_follows_redirects():
    def handler(req):
        if req.url.path == "/jobs/1":
            return httpx.Response(302, headers={"location": "https://a.com/careers"})
        return httpx.Response(200, text=BODY)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await check_many(c, {"k1": "https://a.com/jobs/1", "k2": "https://a.com/jobs/2"},
                                    use_playwright=False)
    assert asyncio.run(go()) == {"k1": "closed", "k2": "open"}
