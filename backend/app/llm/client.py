"""OpenRouter chat client: free-model fallback, throttling, a per-run call budget, JSON output."""

import json
import logging
import re
import time
from typing import Protocol, TypeVar

import openai
from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1"
T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Every model failed for one request."""


class BudgetExceeded(LLMError):
    """The run used up its LLM call budget."""


class LLM(Protocol):
    calls: int

    def complete_json(self, system: str, user: str, schema: type[T]) -> tuple[T, str]:
        """Return the parsed response and the model that produced it."""
        ...


def extract_json(text: str) -> dict:
    """Pull the JSON object out of a reply that may include reasoning or code fences."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start : end + 1])


class OpenRouterLLM:
    def __init__(self, api_key: str, models: list[str], min_interval: float, max_calls: int):
        if not api_key:
            raise LLMError("OPENROUTER_API_KEY is not set (add it to .env)")
        self._client = openai.OpenAI(
            base_url=OPENROUTER_URL, api_key=api_key, timeout=120, max_retries=1,
            default_headers={"X-Title": "job-search-agent"},
        )
        self._models = models
        self._min_interval = min_interval
        self._max_calls = max_calls
        self._last_call = 0.0
        self.calls = 0

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def complete_json(self, system: str, user: str, schema: type[T]) -> tuple[T, str]:
        errors = []
        for model in self._models:
            if self.calls >= self._max_calls:
                raise BudgetExceeded(f"LLM budget of {self._max_calls} calls used")
            self._throttle()
            self.calls += 1
            try:
                response = self._client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                )
                if not response.choices:
                    # OpenRouter reports some provider errors as a 200 with no choices.
                    raise ValueError(f"empty reply: {getattr(response, 'error', None)}")
                text = response.choices[0].message.content or ""
                return schema.model_validate(extract_json(text)), model
            except (openai.APIError, ValueError, ValidationError) as exc:
                # ValidationError subclasses ValueError; both mean "bad output, try next model".
                log.warning("%s failed: %s", model, str(exc)[:300])
                errors.append(f"{model}: {type(exc).__name__}")
        raise LLMError("; ".join(errors))
