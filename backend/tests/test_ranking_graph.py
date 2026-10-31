"""Ranking graph and per-user ranking against the test database, with fake embeddings / LLM."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.config import Settings
from app.db import session_scope
from app.llm.client import BudgetExceeded
from app.llm.schemas import RankResult, ResearchBriefContent
from app.models import Company, Job, JobMatch, LLMUsage, RemoteType, ResearchBrief
from app.ranking import run as run_module
from app.ranking.graph import build_graph
from app.ranking.run import rank_users
from tests.conftest import ADMIN_EMAIL, make_user
from tests.test_ingest import FakeEmbedder

pytestmark = pytest.mark.integration
USD = 88.0


class FakeLLM:
    """Ranks by title keyword; counts calls like the real client."""

    def __init__(self, max_calls: int = 100):
        self.calls = 0
        self.max_calls = max_calls
        self.prompts: list[str] = []

    def complete_json(self, system, user, schema):
        if self.calls >= self.max_calls:
            raise BudgetExceeded("budget")
        self.calls += 1
        self.prompts.append(user)
        if schema is ResearchBriefContent:
            return schema(company_summary="Builds agents.", stage_and_funding="YC W24",
                          lead_project="Invoice Processing Agent", why_lead_project="Docs.",
                          talking_points=["a", "b"]), "fake"
        # Match the job's title line: the resume in the prompt also says "AI Engineer".
        if "Title: AI Engineer" in user:
            return RankResult(tier=1, fit_score=85, reasons=["agents"],
                              india_eligibility="yes"), "fake"
        if "Title: QA Engineer" in user:
            return RankResult(tier=3, fit_score=70, india_eligibility="no",
                              eligibility_evidence="US only"), "fake"
        return RankResult(tier=None, fit_score=10), "fake"


def settings(**overrides) -> Settings:
    values = {"min_similarity": -1.0, "brief_min_score": 50, "llm_max_calls_per_run": 100}
    return Settings(**{**values, **overrides})


def state(resume_id: int, rank_limit: int = 10, brief_limit: int = 5, **extra) -> dict:
    return {"resume_id": resume_id, "about": "", "min_salary_inr": None,
            "rank_limit": rank_limit, "brief_limit": brief_limit, "stats": {}, "errors": [],
            **extra}


@pytest.fixture
def seeded(clean_db):
    with session_scope() as session:
        _, resume = make_user(session, ADMIN_EMAIL, admin=True)
        company = Company(name="Acme", normalized_name="acme")
        for title, salary_usd in (("AI Engineer", 150_000), ("QA Engineer", None),
                                  ("Frontend Engineer", 40_000)):
            session.add(Job(
                source="test", source_job_id=title, url="u", title=title, company=company,
                description=f"{title} job.", dedupe_key=title, passed_filters=True,
                remote_type=RemoteType.REMOTE_UNSPECIFIED, posted_at=datetime.now(UTC),
                salary_max_inr=round(salary_usd * USD) if salary_usd else None,
            ))
        return resume.id


def matches_by_title(session, resume_id=None):
    query = select(Job.title, JobMatch).join(JobMatch, JobMatch.job_id == Job.id)
    if resume_id:
        query = query.where(JobMatch.resume_id == resume_id)
    return {title: match for title, match in session.execute(query)}


def test_ranks_filters_and_briefs(seeded):
    llm = FakeLLM()
    result = build_graph(FakeEmbedder(), llm, settings()).invoke(state(seeded))

    assert result["errors"] == []
    assert result["stats"] == {"candidates": 3, "embedded": 3, "shortlisted": 3,
                               "below_cutoff": 0, "ranked": 3, "deferred": 0, "not_india": 1,
                               "briefs": 1}
    assert llm.calls == 4
    with session_scope() as session:
        matches = matches_by_title(session)
        assert matches["AI Engineer"].tier == 1
        assert matches["Frontend Engineer"].tier is None
        qa = session.scalar(select(Job).where(Job.title == "QA Engineer"))
        assert qa.passed_filters is False
        assert qa.filter_reason == "not open to India (LLM): US only"
        ai = session.scalar(select(Job).where(Job.title == "AI Engineer"))
        assert ai.india_eligible is True
        briefs = session.scalars(select(ResearchBrief)).all()
        assert [(b.job_id, b.resume_id) for b in briefs] == [(ai.id, seeded)]

    # Prompts never contain the resume header (name / email / phone).
    assert all("jane@example.com" not in p and "JANE DOE" not in p for p in llm.prompts)


def test_second_run_does_no_repeat_work(seeded):
    build_graph(FakeEmbedder(), FakeLLM(), settings()).invoke(state(seeded))
    llm = FakeLLM()
    result = build_graph(FakeEmbedder(), llm, settings()).invoke(state(seeded))
    assert result["stats"] == {"candidates": 0}
    assert llm.calls == 0


def test_budget_defers_jobs_to_next_run(seeded):
    # 2 calls total, 1 reserved for briefs: only one job is ranked now.
    llm = FakeLLM(max_calls=2)
    result = build_graph(FakeEmbedder(), llm, settings(llm_max_calls_per_run=2)).invoke(
        state(seeded, brief_limit=1))
    assert (result["stats"]["ranked"], result["stats"]["deferred"]) == (1, 2)
    with session_scope() as session:
        assert len(matches_by_title(session)) == 1
    result = build_graph(FakeEmbedder(), FakeLLM(), settings()).invoke(state(seeded))
    assert result["stats"]["candidates"] == 2


def test_rank_limit_caps_the_shortlist(seeded):
    result = build_graph(FakeEmbedder(), FakeLLM(), settings()).invoke(
        state(seeded, rank_limit=1, brief_limit=0))
    assert (result["stats"]["shortlisted"], result["stats"]["ranked"]) == (1, 1)
    assert "briefs" not in result["stats"]


def test_salary_minimum_keeps_unknown_salaries(seeded):
    result = build_graph(FakeEmbedder(), FakeLLM(), settings()).invoke(
        state(seeded, min_salary_inr=100_000 * USD))
    assert result["stats"]["candidates"] == 2  # AI ($150k) + QA (unknown), not Frontend


def test_low_similarity_jobs_are_recorded_not_ranked(seeded):
    llm = FakeLLM()
    result = build_graph(FakeEmbedder(), llm, settings(min_similarity=1.1)).invoke(state(seeded))
    assert result["stats"]["below_cutoff"] == 3
    assert llm.calls == 0
    with session_scope() as session:
        assert all(m.tier is None for m in matches_by_title(session).values())


# --- rank_users: per-user limits and the overall cap -------------------------------------------

@pytest.fixture
def two_users(seeded, monkeypatch):
    with session_scope() as session:
        _, bob_resume = make_user(session, "bob@example.com", min_salary_usd=100_000,
                                  about="Avoid frontend roles")
    monkeypatch.setattr(run_module, "get_settings", lambda: settings(
        user_daily_rank_limit=2, user_daily_brief_limit=1, llm_daily_cap=800))
    return seeded, bob_resume.id


def test_rank_users_ranks_each_user_within_limits(two_users):
    admin_resume, bob_resume = two_users
    llms = []

    def factory(max_calls):
        llms.append(FakeLLM(max_calls))
        return llms[-1]

    result = rank_users(llm_factory=factory, embedder=FakeEmbedder())
    per_user = result["stats"]["per_user"]
    assert per_user["user 1"]["ranked"] == 2  # daily limit of 2, though 3 candidates
    # Bob: the $40k Frontend job is below his minimum, and QA was already excluded for
    # everyone when user 1's ranking found it closed to India. Only AI Engineer is left.
    assert per_user["user 2"]["candidates"] == 1
    assert "Avoid frontend roles" in llms[1].prompts[0]  # the user's note reaches the AI

    with session_scope() as session:
        assert len(matches_by_title(session, admin_resume)) == 2
        bob_briefs = session.scalars(select(ResearchBrief.resume_id)).all()
        assert bob_briefs.count(bob_resume) <= 1
        usage = {u.user_id: (u.ranked, u.briefs, u.calls)
                 for u in session.scalars(select(LLMUsage))}
    assert usage[1][0] == 2 and usage[1][2] == llms[0].calls

    # Same day again: admin is at the limit; nothing more is ranked for them.
    again = rank_users([1], llm_factory=factory, embedder=FakeEmbedder())
    assert again["stats"]["per_user"]["user 1"].get("ranked", 0) == 0


def test_overall_cap_stops_everyone(two_users, monkeypatch):
    monkeypatch.setattr(run_module, "get_settings", lambda: settings(llm_daily_cap=0))
    result = rank_users(llm_factory=lambda n: FakeLLM(n), embedder=FakeEmbedder())
    assert result["stats"]["per_user"] == {"user 1": {"skipped": "overall daily AI cap reached"}}
