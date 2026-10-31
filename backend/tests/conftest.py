"""Point every test at a separate `jobagent_test` database, created and migrated on demand.

This must run before app.config / app.db are imported, so the real data is never touched.
"""

import os
from pathlib import Path

import pytest

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://jobagent:jobagent@127.0.0.1:5434/jobagent_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
# Test-only sign-in without Google, a fixed session secret, and one known admin.
os.environ["DEV_LOGIN"] = "true"
os.environ["JWT_SECRET"] = "test-secret-" + "x" * 40
os.environ["ADMIN_EMAILS"] = "admin@example.com"
os.environ["GOOGLE_CLIENT_ID"] = ""
os.environ["GOOGLE_CLIENT_SECRET"] = ""

BACKEND_DIR = Path(__file__).resolve().parent.parent
ADMIN_EMAIL = "admin@example.com"


@pytest.fixture
def clean_db():
    """Empty every table (test database only); skips the test if Postgres is down."""
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    from app.db import session_scope

    try:
        with session_scope() as session:
            session.execute(text(
                "TRUNCATE jobs, companies, resumes, users, pipeline_runs, eval_runs, llm_usage "
                "RESTART IDENTITY CASCADE"))
    except OperationalError as exc:
        pytest.skip(f"Postgres not available: {exc}")


def make_user(session, email: str, *, admin: bool = False, min_salary_usd: int | None = None,
              about: str = "", resume_text: str | None = None):
    """A user with an embedded active resume (fake embeddings). Returns (user, resume)."""
    from app.models import User
    from app.resume.ingest import store_resume
    from app.resume.parser import parse_text
    from tests.test_ingest import SAMPLE, FakeEmbedder

    user = User(email=email, name=email.split("@")[0], is_admin=admin,
                min_salary_usd=min_salary_usd, about=about)
    session.add(user)
    session.flush()
    resume = store_resume(session, user.id, parse_text(resume_text or SAMPLE), "cv.pdf",
                          FakeEmbedder())
    return user, resume


def sign_in(client, email: str) -> None:
    response = client.post("/api/auth/dev-login", json={"email": email})
    assert response.status_code == 204, response.text


@pytest.fixture(scope="session", autouse=True)
def test_database():
    """Create and migrate the test database; DB tests skip themselves if Postgres is down."""
    import psycopg
    from alembic.config import Config
    from sqlalchemy.engine import make_url

    from alembic import command

    url = make_url(TEST_DATABASE_URL)
    admin_dsn = (f"postgresql://{url.username}:{url.password}@{url.host}:{url.port}/postgres")
    try:
        with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=3) as conn:
            if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s",
                                (url.database,)).fetchone():
                conn.execute(f'CREATE DATABASE "{url.database}"')
    except psycopg.OperationalError:
        yield
        return

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(config, "head")
    yield
