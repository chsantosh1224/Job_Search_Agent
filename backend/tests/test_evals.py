from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.main import app
from app.db import session_scope
from app.evals.briefs import evaluate_briefs, grounding_checks
from app.evals.ranking import LabeledJob, auc, compute_metrics
from app.evals.run import rank_labeled_jobs, run_ranking_eval
from app.llm.schemas import JudgeResult, RankResult
from app.models import (
    Company,
    EvalLabel,
    Job,
    JobMatch,
    RemoteType,
    ResearchBrief,
    Resume,
    ResumeChunk,
    User,
)
from tests.conftest import ADMIN_EMAIL, sign_in
from tests.test_ingest import FakeEmbedder


def item(job_id, good, tier, score, similarity=0.7, expected_tier=None, ranked=True):
    return LabeledJob(job_id=job_id, title=f"Job {job_id}", company="Acme", good=good,
                      expected_tier=expected_tier, tier=tier, fit_score=score,
                      similarity=similarity, ranked=ranked)


# --- metrics (pure) ---------------------------------------------------------------------------

def test_auc():
    assert auc([0.9, 0.8], [0.1, 0.2]) == 1.0
    assert auc([0.1], [0.9]) == 0.0
    assert auc([0.5], [0.5]) == 0.5
    assert auc([0.9], []) is None


def test_compute_metrics():
    items = [
        item(1, True, 1, 85, 0.80, expected_tier=1),   # agreed good, tier right
        item(2, True, 2, 70, 0.60, expected_tier=1),   # agreed good, tier off by one
        item(3, True, None, 20, 0.75),                 # missed
        item(4, False, 2, 60, 0.82),                   # false alarm
        item(5, False, None, 10, 0.40),                # agreed bad
        item(6, True, None, None, 0.50, ranked=False),  # labeled but never LLM-ranked
    ]
    m = compute_metrics(items, threshold=50)
    assert m["labeled"] == 6 and m["evaluated"] == 5 and m["not_ranked_yet"] == 1
    assert m["confusion"] == {"tp": 2, "fp": 1, "fn": 1, "tn": 1}
    assert m["precision"] == 0.667 and m["recall"] == 0.667 and m["f1"] == 0.667
    assert m["accuracy"] == 0.6
    assert m["precision_at_5"] == 0.6
    assert m["tier_accuracy"] == 0.5 and m["tier_within_one"] == 1.0
    # LLM scores separate good from bad better than raw embedding similarity here:
    # good 85/70/20 vs bad 60/10 -> 5 of 6 pairs ordered correctly.
    assert m["auc_llm"] == 0.833
    assert m["auc_similarity"] == 0.5
    assert {(x["job_id"], x["kind"]) for x in m["mistakes"]} == {
        (3, "false negative"), (4, "false positive")}


def test_metrics_with_no_labels():
    m = compute_metrics([], threshold=50)
    assert m["labeled"] == 0 and m["precision"] is None and m["auc_llm"] is None


def test_grounding_checks():
    resume = SimpleNamespace(raw_text="Built an Invoice Processing Agent",
                             chunks=[SimpleNamespace(title="LangGraph Agentic Platform")])
    brief = {"people": [{"name": "Asha Rao"}, {"name": "Made Up Person"}],
             "lead_project": "LangGraph Agentic Platform"}
    checks = grounding_checks(brief, "Founders: Asha Rao (CEO)", resume)
    assert checks == {"people_not_in_source": ["Made Up Person"], "lead_project_in_resume": True}
    assert grounding_checks({"lead_project": "Quantum Chess Engine"}, "", resume)[
        "lead_project_in_resume"] is False


# --- database ---------------------------------------------------------------------------------

class FakeLLM:
    def __init__(self):
        self.calls = 0

    def complete_json(self, system, user, schema):
        self.calls += 1
        if schema is JudgeResult:
            return JudgeResult(claims=[
                {"claim": "Acme builds agents", "supported": True},
                {"claim": "Acme raised a Series B", "supported": False},
            ], specificity=4, usefulness=3, comment="One invented funding claim."), "judge"
        return RankResult(tier=2, fit_score=72, india_eligibility="unclear"), "ranker"


@pytest.fixture
def seeded(clean_db):
    vector = FakeEmbedder().embed(["x"])[0]
    with session_scope() as session:
        admin = User(email=ADMIN_EMAIL, name="Admin", is_admin=True)
        session.add(admin)
        session.flush()
        resume = Resume(user_id=admin.id, filename="r.pdf", content_hash="h",
                        raw_text="Invoice Processing Agent",
                        sections={"summary": "Automation engineer"}, embedding=vector,
                        is_active=True)
        resume.chunks = [ResumeChunk(position=0, section="experience", title="Invoice agent",
                                     content="Built an invoice agent", embedding=vector)]
        company = Company(name="Acme", normalized_name="acme")
        session.add_all([resume, company])
        session.flush()
        jobs = []
        for title, passed in [("AI Engineer", True), ("QA Engineer", True), ("Unseen", True)]:
            job = Job(source="test", source_job_id=title, url="u", title=title, company=company,
                      description="Acme builds agents.", dedupe_key=title,
                      passed_filters=passed, remote_type=RemoteType.REMOTE_GLOBAL,
                      embedding=vector)
            session.add(job)
            jobs.append(job)
        session.flush()
        # AI Engineer: LLM-ranked + brief. QA Engineer: only a low-similarity record.
        session.add_all([
            JobMatch(job_id=jobs[0].id, resume_id=resume.id, similarity=0.8, tier=1,
                     fit_score=80, reasons=[], gaps=[], model="m"),
            JobMatch(job_id=jobs[1].id, resume_id=resume.id, similarity=0.4, tier=None,
                     reasons=["Low similarity"], gaps=[]),
            ResearchBrief(job_id=jobs[0].id, resume_id=resume.id, model="writer", content={
                "company_summary": "Acme builds agents.", "lead_project": "Invoice Processing Agent",
                "people": [{"name": "Ghost Founder"}], "talking_points": ["a"]}),
            EvalLabel(job_id=jobs[0].id, is_good_fit=True, expected_tier=1),
            EvalLabel(job_id=jobs[1].id, is_good_fit=False),
        ])
        return [j.id for j in jobs]


def test_evaluate_briefs_scores_faithfulness_and_grounding(seeded):
    with session_scope() as session:
        resume = session.scalar(select(Resume))
        result = evaluate_briefs(session, FakeLLM(), resume, limit=5)
    assert result["errors"] == []
    [detail] = result["details"]
    assert detail["faithfulness"] == 0.5
    assert detail["unsupported"] == ["Acme raised a Series B"]
    assert detail["people_not_in_source"] == ["Ghost Founder"]
    assert detail["lead_project_in_resume"] is True
    assert (detail["writer_model"], detail["judge_model"]) == ("writer", "judge")
    assert result["metrics"]["briefs_with_unsupported_claims"] == 1


def test_rank_labeled_jobs_fills_gaps_then_eval_covers_them(seeded):
    assert run_ranking_eval().metrics["not_ranked_yet"] == 1
    llm = FakeLLM()
    assert rank_labeled_jobs(llm, limit=10, embedder=FakeEmbedder()) == {"ranked": 1,
                                                                         "errors": []}
    assert llm.calls == 1  # only the labeled-but-unranked job
    metrics = run_ranking_eval().metrics
    assert metrics["not_ranked_yet"] == 0
    assert metrics["confusion"] == {"tp": 1, "fp": 1, "fn": 0, "tn": 0}


def test_label_api_and_blind_queue(seeded):
    client = TestClient(app)
    sign_in(client, ADMIN_EMAIL)
    unseen = seeded[2]

    queue = client.get("/api/evals/queue").json()
    assert [q["id"] for q in queue] == [unseen]  # labeled jobs are not offered again
    assert not {"tier", "fit_score", "similarity"} & set(queue[0])  # blind to the AI

    saved = client.put(f"/api/jobs/{unseen}/label",
                       json={"is_good_fit": True, "expected_tier": 2}).json()
    assert saved == {"is_good_fit": True, "expected_tier": 2, "notes": ""}
    assert client.get(f"/api/jobs/{unseen}").json()["label"]["expected_tier"] == 2
    assert client.get("/api/evals/queue").json() == []

    # A "not a fit" label drops any tier.
    assert client.put(f"/api/jobs/{unseen}/label",
                      json={"is_good_fit": False, "expected_tier": 2}).json()[
        "expected_tier"] is None
    assert client.put(f"/api/jobs/{unseen}/label",
                      json={"is_good_fit": True, "expected_tier": 7}).status_code == 422

    overview = client.get("/api/evals").json()
    assert overview["ranking"]["labeled"] == 3
    assert overview["label_goal"] == 30

    assert client.delete(f"/api/jobs/{unseen}/label").status_code == 204
    assert client.get(f"/api/jobs/{unseen}").json()["label"] is None
    assert client.post("/api/evals/ranking").status_code == 201
