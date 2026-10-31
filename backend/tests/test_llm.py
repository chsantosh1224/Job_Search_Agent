from types import SimpleNamespace

import openai
import pytest

from app.llm.client import BudgetExceeded, LLMError, OpenRouterLLM, extract_json
from app.llm.schemas import RankResult, ResearchBriefContent


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        '<think>Let me consider {"b": 2}</think>{"a": 1}',
        'Here is the result: {"a": 1} Hope this helps.',
    ],
)
def test_extract_json(text):
    assert extract_json(text) == {"a": 1}


def test_extract_json_without_object_raises():
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_rank_result_absorbs_free_model_quirks():
    result = RankResult.model_validate({
        "tier": "2", "fit_score": "87.5", "reasons": "Strong agent experience",
        "gaps": None, "india_eligibility": "Yes",
    })
    assert result.tier == 2
    assert result.fit_score == 87
    assert result.reasons == ["Strong agent experience"]
    assert result.gaps == []
    assert result.india_eligibility == "yes"


@pytest.mark.parametrize("tier", [0, 4, "none", None, "N/A"])
def test_rank_result_invalid_tier_means_not_a_fit(tier):
    assert RankResult.model_validate({"tier": tier, "fit_score": 10}).tier is None


def test_rank_result_clamps_score():
    assert RankResult.model_validate({"tier": 1, "fit_score": 140}).fit_score == 100


def test_brief_tolerates_missing_secondary_fields():
    brief = ResearchBriefContent.model_validate({
        "company_summary": "x", "lead_project": "Invoice Processing Agent",
        "talking_points": ["a"],
    })
    assert brief.stage_and_funding == "Not stated in the posting"
    assert brief.why_lead_project == ""


def test_brief_still_requires_core_content():
    with pytest.raises(ValueError):
        ResearchBriefContent.model_validate({"company_summary": "x", "talking_points": ["a"]})


def test_brief_drops_people_without_names():
    brief = ResearchBriefContent.model_validate({
        "company_summary": "x", "stage_and_funding": "Not stated in the posting",
        "people": [{"name": "Asha Rao", "role": "CEO"}, {"role": "CTO"}, "junk"],
        "lead_project": "Invoice Processing Agent", "why_lead_project": "y",
        "talking_points": ["a", "b"],
    })
    assert [p.name for p in brief.people] == ["Asha Rao"]


class FakeCompletions:
    def __init__(self, replies):
        self.replies = list(replies)
        self.models = []

    def create(self, model, **kwargs):
        self.models.append(model)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, SimpleNamespace):  # a raw response object
            return reply
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])


def make_llm(replies, models=("m1", "m2", "m3"), max_calls=10):
    llm = OpenRouterLLM("key", list(models), min_interval=0, max_calls=max_calls)
    completions = FakeCompletions(replies)
    llm._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return llm, completions


GOOD = '{"tier": 1, "fit_score": 80}'


def test_falls_back_to_next_model_on_bad_json_and_api_error():
    api_error = openai.APIStatusError(
        "rate limited", response=SimpleNamespace(status_code=429, headers={},
                                                 request=None), body=None)
    llm, completions = make_llm(["not json", api_error, GOOD])
    result, model = llm.complete_json("s", "u", RankResult)
    assert (result.tier, model) == (1, "m3")
    assert completions.models == ["m1", "m2", "m3"]
    assert llm.calls == 3


def test_reply_without_choices_falls_back():
    llm, _ = make_llm([SimpleNamespace(choices=None, error={"code": 502}), GOOD])
    result, model = llm.complete_json("s", "u", RankResult)
    assert (result.tier, model) == (1, "m2")


def test_all_models_failing_raises():
    llm, _ = make_llm(["x", "y", "z"])
    with pytest.raises(LLMError):
        llm.complete_json("s", "u", RankResult)


def test_budget_is_enforced():
    llm, _ = make_llm([GOOD, GOOD], max_calls=1)
    llm.complete_json("s", "u", RankResult)
    with pytest.raises(BudgetExceeded):
        llm.complete_json("s", "u", RankResult)


def test_missing_api_key_is_a_clear_error():
    with pytest.raises(LLMError, match="OPENROUTER_API_KEY"):
        OpenRouterLLM("", ["m"], 0, 1)
