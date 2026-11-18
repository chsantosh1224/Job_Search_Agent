"""Phase 3: is the job still open?

Jobs seen on a board API this run are live by definition and are skipped. Everything else is
fetched (httpx; Playwright fallback for JS-rendered pages when installed) and marked closed on
404/410, a redirect away from the posting, Greenhouse ?error=true, or closed-job wording.
"""

import asyncio
import logging
import re
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

CLOSED_PHRASES = [
    "no longer accepting", "no longer available", "no longer open", "position has been filled",
    "job is closed", "job has been closed", "posting has closed", "this job has expired",
    "job posting has expired", "posting has expired", "job is no longer", "job has expired",
    "this position is closed", "position is no longer", "the page you are looking for doesn't exist",
    "job not found", "this requisition is no longer", "role has been filled",
]
_SCRIPT = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
MIN_TEXT = 400  # below this the page is probably a JS shell; try Playwright


def page_text(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub(" ", _SCRIPT.sub(" ", html))).strip().lower()


def text_says_closed(text: str) -> bool:
    return any(p in text for p in CLOSED_PHRASES)


def redirected_away(original: str, final: str) -> bool:
    """Redirected to a page that no longer carries the posting's id (e.g. the careers home)."""
    o, f = urlsplit(original), urlsplit(final)
    if (o.netloc, o.path.rstrip("/")) == (f.netloc, f.path.rstrip("/")):
        return False
    segs = [s for s in o.path.split("/") if s]
    ident = next((s for s in reversed(segs) if re.search(r"\d", s)), segs[-1] if segs else "")
    return bool(ident) and ident not in final


def classify(original: str, status: int, final_url: str, html: str) -> str:
    if status in (404, 410):
        return "closed"
    if "error=true" in urlsplit(final_url).query:
        return "closed"
    if status >= 400:
        return "unknown"  # 403/429/5xx: blocked or flaky, not evidence of closure
    if final_url != original and redirected_away(original, final_url):
        return "closed"
    text = page_text(html)
    if text_says_closed(text):
        return "closed"
    return "open" if len(text) >= MIN_TEXT else "unknown"


class Renderer:
    """Lazy shared Playwright browser; disabled if Playwright isn't installed."""

    def __init__(self):
        self._pw = self._browser = None
        self.available = True
        self._lock = asyncio.Lock()

    async def html(self, url: str) -> tuple[int, str, str] | None:
        async with self._lock:
            if self._browser is None and self.available:
                try:
                    from playwright.async_api import async_playwright
                    self._pw = await async_playwright().start()
                    self._browser = await self._pw.chromium.launch()
                except Exception as e:  # not installed / no browsers downloaded
                    log.info("Playwright unavailable (%s); JS pages stay 'unknown'", e)
                    self.available = False
        if not self._browser:
            return None
        page = await self._browser.new_page()
        try:
            resp = await page.goto(url, wait_until="networkidle", timeout=30000)
            return (resp.status if resp else 0), page.url, await page.content()
        except Exception as e:
            log.debug("render failed %s: %s", url, e)
            return None
        finally:
            await page.close()

    async def close(self):
        if self._browser:
            await self._browser.close()
            await self._pw.stop()


async def check(client: httpx.AsyncClient, url: str, renderer: Renderer | None = None) -> str:
    try:
        r = await client.get(url, follow_redirects=True)
        result = classify(url, r.status_code, str(r.url), r.text)
    except httpx.HTTPError as e:
        log.debug("fetch failed %s: %s", url, e)
        result = "unknown"
    if result == "unknown" and renderer is not None:
        rendered = await renderer.html(url)
        if rendered:
            result = classify(url, *rendered)
    return result


async def check_many(
    client: httpx.AsyncClient, urls: dict[str, str], concurrency: int = 5, use_playwright: bool = True,
    on_result=None,
) -> dict[str, str]:
    """urls: key → url. Returns key → open|closed|unknown. on_result(key, status) after each check."""
    sem = asyncio.Semaphore(concurrency)
    renderer = Renderer() if use_playwright else None

    async def one(key: str, url: str):
        async with sem:
            status = await check(client, url, renderer)
        if on_result:
            on_result(key, status)
        return key, status

    try:
        return dict(await asyncio.gather(*(one(k, u) for k, u in urls.items())))
    finally:
        if renderer:
            await renderer.close()
