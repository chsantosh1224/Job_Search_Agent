import logging
import time

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; job-search-agent/0.1; personal use)"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class HttpClient:
    """httpx client with retries on transport errors (incl. flaky TLS) and 429/5xx."""

    def __init__(self, attempts: int = 4, backoff: float = 1.5, min_interval: float = 0.0):
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=45, follow_redirects=True
        )
        self._attempts = attempts
        self._backoff = backoff
        self._min_interval = min_interval  # politeness delay between requests
        self._last_request = 0.0

    def get(self, url: str, **params) -> httpx.Response:
        for attempt in range(1, self._attempts + 1):
            wait = self._min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            try:
                response = self._client.get(url, params=params or None)
                if response.status_code not in RETRY_STATUSES:
                    response.raise_for_status()
                    return response
                error: Exception = httpx.HTTPStatusError(
                    f"HTTP {response.status_code}", request=response.request, response=response
                )
            except httpx.TransportError as exc:
                error = exc
            if attempt == self._attempts:
                raise error
            log.warning("GET %s failed (%s), retry %d", url, error, attempt)
            time.sleep(self._backoff * 2 ** (attempt - 1))
        raise AssertionError("unreachable")

    def json(self, url: str, **params):
        return self.get(url, **params).json()

    def text(self, url: str, **params) -> str:
        return self.get(url, **params).text

    def close(self) -> None:
        self._client.close()
