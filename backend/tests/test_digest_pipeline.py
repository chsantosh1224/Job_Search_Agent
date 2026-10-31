"""Digest, pipeline runner and scheduling, against the test database."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, text

from app.config import Settings
from app.db import engine, session_scope
from app.digest import collect, render_html, render_text, send_digest, send_digests
from app.models import Company, Job, JobMatch, PipelineRun, RemoteType, ResearchBrief, User
from app.pipeline import (
    IST,
    PIPELINE_LOCK_ID,
    execute_run,
    fail_stale_runs,
    next_daily_run,
    queue_run,
)
from tests.conftest import ADMIN_EMAIL, make_user

SETTINGS = Settings(resend_api_key="re_test", public_url="https://jobs.example.test/",
                    digest_max_jobs=10)


@pytest.fixture
def db(clean_db):
    return None


@pytest.fixture
def matches(clean_db):
    with session_scope() as session:
        user, resume = make_user(session, ADMIN_EMAIL, admin=True)
        company = Company(name="Acme <Labs>", normalized_name="acme")
        session.add(company)
        session.flush()
        specs = [  # title, tier, score, already emailed, passed filters
            ("AI Engineer <script>alert(1)</script>", 1, 85, False, True),
            ("QA Engineer", 3, 60, False, True),
            ("Agent Engineer", 2, 70, True, True),
            ("Product Engineer", None, 20, False, True),
            ("US-only AI Engineer", 1, 90, False, False),
        ]
        for title, tier, score, notified, passed in specs:
            job = Job(source="test", source_job_id=title, url="u", title=title, company=company,
                      description="", dedupe_key=title, passed_filters=passed,
                      remote_type=RemoteType.REMOTE_GLOBAL, salary_min_inr=4_000_000,
                      salary_max_inr=6_000_000)
            session.add(job)
            session.flush()
            session.add(JobMatch(job_id=job.id, resume_id=resume.id, similarity=0.8, tier=tier,
                                 fit_score=score, reasons=["Strong agent work"], gaps=[],
                                 model="m",
                                 notified_at=datetime.now(UTC) if notified else None))
            if tier == 1:
                session.add(ResearchBrief(job_id=job.id, resume_id=resume.id, model="m",
                                          content={"lead_project": "Invoice Processing Agent"}))
        return user.id


def admin(session) -> User:
    return session.scalar(select(User).where(User.email == ADMIN_EMAIL))


def test_collect_returns_new_tiered_passing_matches_best_first(matches):
    with session_scope() as session:
        items, total = collect(session, admin(session), limit=10)
        assert [i.job.title.split()[0] for i in items] == ["AI", "QA"]
        assert total == 2
        assert items[0].salary == "$45k–$68k"  # ₹40-60 lakh at 88 INR/USD


def test_rendering_escapes_job_text(matches):
    with session_scope() as session:
        items, total = collect(session, admin(session), limit=10)
        body = render_html(items, total, "https://jobs.example.test")
        text_body = render_text(items, total, "https://jobs.example.test")
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
    assert "Acme &lt;Labs&gt;" in body
    assert "Lead with: <b>Invoice Processing Agent</b>" in body
    assert "https://jobs.example.test/jobs/1" in body
    assert "Lead with: Invoice Processing Agent" in text_body


def test_send_marks_matches_and_sends_only_once(matches):
    sent = []
    with session_scope() as session:
        result = send_digest(session, admin(session),
                             lambda s, to, subj, h, t: sent.append((to, subj)), SETTINGS)
    assert result == {"sent": True, "jobs": 2, "new_matches": 2}
    assert sent == [(ADMIN_EMAIL, "2 new job matches (best: Tier 1)")]
    with session_scope() as session:
        assert send_digest(session, admin(session), lambda *a: sent.append("again"),
                           SETTINGS) == {"sent": False, "reason": "no new matches"}
    assert len(sent) == 1


def test_digests_go_to_each_user_separately(matches):
    with session_scope() as session:
        make_user(session, "bob@example.com")  # no matches yet
    sent = []
    with session_scope() as session:
        result = send_digests(session, lambda s, to, *a: sent.append(to), SETTINGS)
    assert sent == [ADMIN_EMAIL]
    assert result["sent"] == 1
    assert result["per_user"]["user 2"] == {"sent": False, "reason": "no new matches"}


def test_failed_send_keeps_matches_for_next_time(matches):
    def failing(*args):
        raise httpx.ConnectError("down")

    with session_scope() as session:
        assert send_digest(session, admin(session), failing, SETTINGS)["sent"] is False
    with session_scope() as session:
        assert collect(session, admin(session), limit=10)[1] == 2


def test_digest_not_configured(matches):
    with session_scope() as session:
        result = send_digest(session, admin(session), lambda *a: None,
                             Settings(resend_api_key=""))
    assert result["sent"] is False and "not configured" in result["reason"]


# --- scheduling -------------------------------------------------------------------------------

def test_next_daily_run_today_and_tomorrow():
    morning = datetime(2026, 10, 27, 3, 0, tzinfo=IST)
    assert next_daily_run(morning, "05:00") == datetime(2026, 10, 27, 5, 0, tzinfo=IST)
    after = datetime(2026, 10, 27, 5, 0, tzinfo=IST)
    assert next_daily_run(after, "05:00") == datetime(2026, 10, 28, 5, 0, tzinfo=IST)
    # Works from a UTC clock too (the server's).
    utc = datetime(2026, 10, 26, 22, 0, tzinfo=UTC)  # 03:30 IST on the 27th
    assert next_daily_run(utc, "05:00") == datetime(2026, 10, 27, 5, 0, tzinfo=IST)


# --- pipeline runner --------------------------------------------------------------------------

def ok_steps(calls):
    return {
        "fetch": lambda: calls.append("fetch") or {"yc": {"fetched": 3}},
        "rank": lambda user_ids: calls.append(("rank", user_ids)) or {
            "stats": {"ranked": 2}, "errors": []},
        "digest": lambda session: calls.append("digest") or {"sent": 1},
    }


def test_queue_run_refuses_while_one_is_active(db):
    first = queue_run("manual")
    assert first is not None and first.status == "queued"
    assert queue_run("manual") is None


def test_user_runs_queue_alongside_the_daily_run(db):
    with session_scope() as session:
        user, _ = make_user(session, "bob@example.com")
    assert queue_run("manual") is not None
    assert queue_run("resume", user_id=user.id) is not None  # not blocked by the global run
    assert queue_run("resume", user_id=user.id) is None  # but one per user at a time


def test_execute_runs_all_steps_in_order(db):
    calls = []
    run = execute_run(queue_run("manual").id, **ok_steps(calls))
    assert calls == ["fetch", ("rank", None), "digest"]
    assert run.status == "success"
    assert run.stats == {"errors": [], "fetch": {"yc": {"fetched": 3}},
                         "rank": {"ranked": 2}, "digest": {"sent": 1}}
    assert queue_run("manual") is not None  # finished runs no longer block


def test_user_run_only_ranks_that_user(db):
    with session_scope() as session:
        user, _ = make_user(session, "bob@example.com")
    calls = []
    run = execute_run(queue_run("resume", user_id=user.id).id, **ok_steps(calls))
    assert calls == [("rank", [user.id])]  # no fetch, no digest
    assert run.status == "success"


def test_source_error_makes_run_partial(db):
    steps = ok_steps([])
    steps["fetch"] = lambda: {"yc": {"error": "boom"}, "hackernews": {"fetched": 1}}
    assert execute_run(queue_run("manual").id, **steps).status == "partial"


def test_crashing_step_fails_run_with_error(db):
    steps = ok_steps([])

    def crash(user_ids):
        raise RuntimeError("ranking exploded")

    steps["rank"] = crash
    run = execute_run(queue_run("manual").id, **steps)
    assert run.status == "failed"
    assert run.stats["errors"] == ["RuntimeError: ranking exploded"]
    assert "yc" in run.stats["fetch"]  # progress before the crash is kept


def test_run_is_skipped_while_another_holds_the_lock(db):
    run_id = queue_run("manual").id
    calls = []
    with engine.connect() as other:
        other.execute(text("SELECT pg_advisory_lock(:id)"), {"id": PIPELINE_LOCK_ID})
        run = execute_run(run_id, **ok_steps(calls))
        other.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": PIPELINE_LOCK_ID})
    assert run.status == "skipped"
    assert calls == []


def test_stale_runs_are_failed(db):
    run = queue_run("manual")
    assert fail_stale_runs(now=datetime.now(UTC)) == 0
    assert fail_stale_runs(now=datetime.now(UTC) + timedelta(hours=4)) == 1
    with session_scope() as session:
        assert session.scalar(select(PipelineRun.status).where(PipelineRun.id == run.id)) == (
            "failed")
