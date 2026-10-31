"""Integration tests: need Postgres running (docker compose up -d db) and migrations applied."""

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.models import EMBEDDING_DIM, Resume
from app.resume import ingest as ingest_module
from app.resume.parser import parse_text
from tests.test_parser import SAMPLE

pytestmark = pytest.mark.integration


class FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            seed = int(hashlib.md5(text.encode()).hexdigest(), 16)
            vectors.append([((seed >> (i % 64)) & 1) * 1.0 + 0.01 for i in range(EMBEDDING_DIM)])
        return vectors


@pytest.fixture
def session():
    """Session whose work is rolled back, so tests never touch real data."""
    from app.db import SessionLocal

    session = SessionLocal()
    try:
        session.execute(select(1))
    except OperationalError as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Postgres not available: {exc}")
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def sample_pdf(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest_module, "parse_resume", lambda path: parse_text(SAMPLE))
    return tmp_path / "jane.pdf"


def test_ingest_creates_active_resume_with_embedded_chunks(session, sample_pdf: Path):
    resume = ingest_module.ingest_resume(session, sample_pdf, FakeEmbedder())

    assert resume.is_active
    assert len(resume.chunks) == 7  # summary, 2 skills, 3 experience, education
    assert all(len(chunk.embedding) == EMBEDDING_DIM for chunk in resume.chunks)
    assert len(resume.embedding) == EMBEDDING_DIM


def test_reingesting_same_resume_reuses_row(session, sample_pdf: Path):
    first = ingest_module.ingest_resume(session, sample_pdf, FakeEmbedder())
    second = ingest_module.ingest_resume(session, sample_pdf, FakeEmbedder())

    assert first.id == second.id
    assert session.scalar(select(Resume).where(Resume.user_id.is_(None),
                                               Resume.is_active.is_(True))).id == first.id
