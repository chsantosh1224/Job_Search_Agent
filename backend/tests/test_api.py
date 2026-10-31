"""API tests against the test database (multi-user, dev sign-in instead of Google)."""

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import auth as auth_module
from app.api import profile as profile_module
from app.api.auth import _safe_next
from app.api.main import app
from app.config import Settings, get_settings
from app.db import session_scope
from app.models import (
    Application,
    Company,
    Job,
    JobMatch,
    PipelineRun,
    RemoteType,
    ResearchBrief,
    Resume,
    User,
)
from app.resume.parser import parse_text
from tests.conftest import ADMIN_EMAIL, make_user, sign_in
from tests.test_ingest import SAMPLE

USD = 88.0


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def new_client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def world(clean_db):
    """Two users (admin + regular) and jobs with different salaries and regions."""
    with session_scope() as session:
        admin, admin_resume = make_user(session, ADMIN_EMAIL, admin=True)
        alice, alice_resume = make_user(session, "alice@example.com")
        company = Company(name="Acme", normalized_name="acme", website="https://acme.dev")
        session.add(company)
        specs = [  # title, passed, region, salary USD range
            ("AI Engineer", True, RemoteType.REMOTE_GLOBAL, (120_000, 150_000)),
            ("QA Engineer", True, RemoteType.REMOTE_INDIA, (40_000, 60_000)),
            ("Agent Engineer", True, RemoteType.REMOTE_UNSPECIFIED, None),
            ("Data Engineer", False, RemoteType.ONSITE, None),
        ]
        jobs = {}
        for title, passed, region, salary in specs:
            jobs[title] = Job(
                source="test", source_job_id=title, url=f"https://acme.dev/{title}",
                title=title, company=company, description=f"{title} building agents.",
                dedupe_key=title, passed_filters=passed,
                filter_reason=None if passed else "not remote (onsite)",
                remote_type=region, posted_at=datetime.now(UTC),
                salary_min_inr=round(salary[0] * USD) if salary else None,
                salary_max_inr=round(salary[1] * USD) if salary else None,
            )
            session.add(jobs[title])
        session.flush()
        # Admin's ranking: AI tier 1 (with brief), QA tier 3. Alice: only Agent, tier 2.
        session.add_all([
            JobMatch(job_id=jobs["AI Engineer"].id, resume_id=admin_resume.id, similarity=0.8,
                     tier=1, fit_score=85, reasons=["agents"], gaps=["TypeScript"], model="m"),
            JobMatch(job_id=jobs["QA Engineer"].id, resume_id=admin_resume.id, similarity=0.7,
                     tier=3, fit_score=60, reasons=[], gaps=[], model="m"),
            JobMatch(job_id=jobs["Agent Engineer"].id, resume_id=alice_resume.id,
                     similarity=0.7, tier=2, fit_score=70, reasons=[], gaps=[], model="m"),
            ResearchBrief(job_id=jobs["AI Engineer"].id, resume_id=admin_resume.id, model="m",
                          content={"lead_project": "Invoice Processing Agent"}),
        ])
        return {"jobs": {t: j.id for t, j in jobs.items()}, "admin": admin.id,
                "alice": alice.id}


# --- sign-in ----------------------------------------------------------------------------------

def test_api_requires_sign_in(client):
    assert client.get("/api/jobs").status_code == 401
    assert client.get("/api/me").status_code == 401


def test_dev_login_is_off_unless_enabled(client, clean_db):
    app.dependency_overrides[get_settings] = lambda: Settings(dev_login=False,
                                                              jwt_secret="s" * 40)
    assert client.post("/api/auth/dev-login", json={"email": "a@b.c"}).status_code == 404


def test_sign_in_cookie_and_logout(client, clean_db):
    response = client.post("/api/auth/dev-login", json={"email": "bob@example.com"})
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    me = client.get("/api/me").json()
    assert (me["email"], me["is_admin"], me["resume"]) == ("bob@example.com", False, None)
    client.post("/api/auth/logout")
    assert client.get("/api/me").status_code == 401


def test_admin_email_gets_admin(client, clean_db):
    sign_in(client, ADMIN_EMAIL)
    assert client.get("/api/me").json()["is_admin"] is True


def test_google_not_configured(client):
    assert client.get("/api/auth/config").json() == {"google": False, "dev_login": True}
    assert client.get("/api/auth/google/login", follow_redirects=False).status_code == 503


@pytest.mark.parametrize("path, expected", [
    ("/jobs/12", "/jobs/12"), ("//evil.com", "/jobs"), ("https://evil.com", "/jobs"),
    (None, "/jobs"), ("/\\evil.com", "/jobs"),
])
def test_next_path_is_same_site_only(path, expected):
    assert _safe_next(path) == expected


def google_settings():
    return Settings(google_client_id="cid", google_client_secret="secret",
                    jwt_secret="s" * 40, public_url="https://jobs.example.test",
                    admin_emails=ADMIN_EMAIL)


def test_google_flow_signs_in_and_links_account(client, clean_db, monkeypatch):
    app.dependency_overrides[get_settings] = google_settings
    start = client.get("/api/auth/google/login?next=/jobs/7", follow_redirects=False)
    assert start.status_code == 302
    location = urlparse(start.headers["location"])
    params = parse_qs(location.query)
    assert location.netloc == "accounts.google.com"
    assert params["redirect_uri"] == ["https://jobs.example.test/api/auth/google/callback"]

    class TokenResponse:
        def raise_for_status(self): ...
        def json(self): return {"id_token": "token"}

    monkeypatch.setattr(auth_module.httpx, "post", lambda *a, **k: TokenResponse())
    monkeypatch.setattr(auth_module, "verify_google_id_token", lambda token, cid: {
        "sub": "google-123", "email": "Carol@Example.com", "email_verified": True,
        "name": "Carol", "nonce": params["nonce"][0]})

    done = client.get(f"/api/auth/google/callback?code=c&state={params['state'][0]}",
                      follow_redirects=False)
    assert (done.status_code, done.headers["location"]) == (302, "/jobs/7")
    assert client.get("/api/me").json()["email"] == "carol@example.com"
    with session_scope() as session:
        assert session.scalar(select(User.google_sub)) == "google-123"


def test_google_callback_rejects_wrong_state_and_bad_nonce(client, clean_db, monkeypatch):
    app.dependency_overrides[get_settings] = google_settings
    start = client.get("/api/auth/google/login", follow_redirects=False)
    params = parse_qs(urlparse(start.headers["location"]).query)

    wrong = client.get("/api/auth/google/callback?code=c&state=forged", follow_redirects=False)
    assert wrong.headers["location"] == "/login?error=state"
    # A failed attempt consumes the one-time state; start a fresh sign-in.
    start = client.get("/api/auth/google/login", follow_redirects=False)
    params = parse_qs(urlparse(start.headers["location"]).query)

    class TokenResponse:
        def raise_for_status(self): ...
        def json(self): return {"id_token": "token"}

    monkeypatch.setattr(auth_module.httpx, "post", lambda *a, **k: TokenResponse())
    monkeypatch.setattr(auth_module, "verify_google_id_token", lambda token, cid: {
        "sub": "x", "email": "x@example.com", "email_verified": True, "nonce": "replayed"})
    replay = client.get(f"/api/auth/google/callback?code=c&state={params['state'][0]}",
                        follow_redirects=False)
    assert replay.headers["location"] == "/login?error=unverified"
    assert client.get("/api/me").status_code == 401


# --- profile ----------------------------------------------------------------------------------

def test_profile_update_and_resume_upload(client, clean_db, monkeypatch):
    sign_in(client, "dana@example.com")
    profile = client.put("/api/me", json={"name": "Dana", "about": "Pivoting to AI",
                                          "min_salary_usd": 90000}).json()
    assert (profile["name"], profile["min_salary_usd"]) == ("Dana", 90000)
    assert client.put("/api/me", json={"name": "D", "min_salary_usd": -1}).status_code == 422

    pdf = {"file": ("cv.pdf", b"%PDF-1.4 fake", "application/pdf")}
    assert client.post("/api/me/resume", files=pdf).status_code == 409  # consent first
    client.post("/api/me/consent")
    not_pdf = {"file": ("cv.docx", b"PK\x03\x04", "application/octet-stream")}
    assert client.post("/api/me/resume", files=not_pdf).status_code == 415

    monkeypatch.setattr(profile_module, "parse_resume", lambda stream: parse_text(SAMPLE))
    uploaded = client.post("/api/me/resume", files=pdf).json()
    assert uploaded["resume"]["filename"] == "cv.pdf"
    assert uploaded["resume"]["ready"] is False  # the worker embeds it
    with session_scope() as session:
        run = session.scalar(select(PipelineRun))
        assert (run.status, run.trigger, run.user_id) == ("queued", "resume", uploaded["id"])


def test_delete_account_removes_data(client, world):
    sign_in(client, "alice@example.com")
    job_id = world["jobs"]["Agent Engineer"]
    client.put(f"/api/jobs/{job_id}/application", json={"status": "applied"})
    assert client.delete("/api/me").status_code == 204
    assert client.get("/api/me").status_code == 401
    with session_scope() as session:
        assert session.get(User, world["alice"]) is None
        assert session.scalar(select(Resume).where(Resume.user_id == world["alice"])) is None
        assert session.scalar(select(Application)) is None
        assert session.scalar(select(JobMatch).where(JobMatch.job_id == job_id)) is None


# --- jobs, per user ---------------------------------------------------------------------------

def titles(response) -> list[str]:
    return [j["title"] for j in response.json()]


def test_each_user_sees_only_their_rankings_and_briefs(client, world):
    sign_in(client, ADMIN_EMAIL)
    assert titles(client.get("/api/jobs")) == ["AI Engineer", "QA Engineer"]
    assert client.get("/api/jobs").json()[0]["has_brief"] is True

    other = new_client()
    sign_in(other, "alice@example.com")
    assert titles(other.get("/api/jobs")) == ["Agent Engineer"]
    detail = other.get(f"/api/jobs/{world['jobs']['AI Engineer']}").json()
    assert (detail["tier"], detail["brief"], detail["reasons"]) == (None, None, [])


def test_tracker_is_per_user(client, world):
    sign_in(client, ADMIN_EMAIL)
    job_id = world["jobs"]["QA Engineer"]
    client.put(f"/api/jobs/{job_id}/application", json={"status": "applied", "notes": "x"})
    assert [j["id"] for j in client.get("/api/jobs?view=tracked").json()] == [job_id]

    other = new_client()
    sign_in(other, "alice@example.com")
    assert other.get("/api/jobs?view=tracked").json() == []
    assert other.get(f"/api/jobs/{job_id}").json()["status"] is None


def test_salary_filter_in_usd_with_unknown_checkbox(client, world):
    sign_in(client, ADMIN_EMAIL)
    base = "/api/jobs?view=other"  # admin's unranked + no-tier jobs: Agent Engineer only
    ranked = "/api/jobs"
    assert titles(client.get(f"{ranked}?salary_min_usd=100000")) == ["AI Engineer"]
    assert titles(client.get(f"{ranked}?salary_max_usd=70000")) == ["QA Engineer"]
    assert titles(client.get(f"{ranked}?salary_min_usd=55000&salary_max_usd=130000")) == [
        "AI Engineer", "QA Engineer"]  # ranges overlap
    assert titles(client.get(f"{base}")) == ["Agent Engineer"]  # salary unknown, included
    assert titles(client.get(f"{base}&include_unknown_salary=false")) == []
    salaries = client.get(ranked).json()[0]
    assert (salaries["salary_min_usd"], salaries["salary_max_usd"]) == (120_000, 150_000)


def test_region_filter(client, world):
    sign_in(client, ADMIN_EMAIL)
    assert titles(client.get("/api/jobs?region=india")) == ["QA Engineer"]
    assert titles(client.get("/api/jobs?region=worldwide&region=india")) == [
        "AI Engineer", "QA Engineer"]
    assert titles(client.get("/api/jobs?view=other&region=unspecified")) == ["Agent Engineer"]
    assert client.get("/api/jobs?region=mars").status_code == 422
    # Filtered-out jobs are listed with their reason regardless of filters.
    assert titles(client.get("/api/jobs?view=filtered&region=india")) == ["Data Engineer"]


def test_summary_is_per_user(client, world):
    sign_in(client, "alice@example.com")
    summary = client.get("/api/summary").json()
    assert (summary["tiers"], summary["briefs"], summary["runs"]) == ({"2": 1}, 0, [])


# --- admin ------------------------------------------------------------------------------------

def test_admin_only_endpoints(client, world):
    sign_in(client, "alice@example.com")
    for method, path in [("post", "/api/runs"), ("get", "/api/admin/users"),
                         ("get", "/api/evals"), ("get", "/api/evals/queue")]:
        assert getattr(client, method)(path).status_code == 403, path

    admin = new_client()
    sign_in(admin, ADMIN_EMAIL)
    assert admin.post("/api/runs").status_code == 202
    assert admin.post("/api/runs").status_code == 409
    users = admin.get("/api/admin/users").json()
    assert {u["email"] for u in users["users"]} == {ADMIN_EMAIL, "alice@example.com"}
    assert users["daily_cap"] == 800


def test_disabling_a_user_blocks_them(client, world):
    admin = new_client()
    sign_in(admin, ADMIN_EMAIL)
    sign_in(client, "alice@example.com")
    assert admin.put(f"/api/admin/users/{world['alice']}",
                     json={"is_active": False}).status_code == 200
    assert client.get("/api/jobs").status_code == 403
    assert client.post("/api/auth/dev-login",
                       json={"email": "alice@example.com"}).status_code == 403
    assert admin.put(f"/api/admin/users/{world['admin']}",
                     json={"is_active": False}).status_code == 400
