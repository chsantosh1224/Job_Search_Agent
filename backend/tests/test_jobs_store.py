"""Integration tests: need Postgres running with migrations applied."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.jobs_store import StoreStats, ats_boards, store_job
from app.models import Company, Job, RemoteType
from app.normalize.salary import parse_salary
from app.sources.base import RawJob
from tests.test_ingest import session  # noqa: F401 - shared rollback fixture

pytestmark = pytest.mark.integration


def raw(**overrides) -> RawJob:
    values = {
        "source": "test", "source_job_id": "1", "url": "https://example.com/1", "title": "AI Engineer",
        "company_name": "Zeta Test Co", "description": "Build agents.", "location": "Remote (IN)",
        "posted_at": datetime.now(UTC),
    }
    return RawJob(**{**values, **overrides})


def test_stores_classifies_and_passes(session):  # noqa: F811
    stats = StoreStats()
    job = store_job(session, raw(salary=parse_salary("₹40L - ₹60L")), stats)
    assert job.passed_filters and job.filter_reason is None
    assert job.remote_type == RemoteType.REMOTE_INDIA
    assert job.salary_max_inr == 6_000_000
    assert job.company.name == "Zeta Test Co"
    assert stats.as_dict() == {"fetched": 1, "off_target": 0, "new": 1, "updated": 0,
                               "passed": 1, "errors": 0}


def test_off_target_roles_are_not_stored_but_boards_are_discovered(session):  # noqa: F811
    stats = StoreStats()
    result = store_job(session, raw(title="Account Executive",
                                    ats_links={("ashby", "zetatest")}), stats)
    assert result is None and stats.off_target == 1
    assert ("ashby", "zetatest", "Zeta Test Co") in ats_boards(session)


def test_refetch_updates_without_erasing_details(session):  # noqa: F811
    stats = StoreStats()
    first = store_job(session, raw(extra={"hiring_manager": "Asha"}), stats)
    again = store_job(session, raw(description="", extra={}), stats)
    assert again.id == first.id
    assert again.description == "Build agents."
    assert again.extra == {"hiring_manager": "Asha"}
    assert (stats.new, stats.updated) == (1, 1)


def test_cross_source_duplicate_is_flagged(session):  # noqa: F811
    stats = StoreStats()
    original = store_job(session, raw(), stats)
    duplicate = store_job(session, raw(source="other", company_name="Zeta Test Co, Inc."), stats)
    assert duplicate.passed_filters is False
    assert duplicate.filter_reason == f"duplicate of job #{original.id}"


def test_refetch_keeps_llm_india_exclusion(session):  # noqa: F811
    job = store_job(session, raw(location="Remote"), StoreStats())
    assert job.passed_filters  # rules alone see nothing wrong
    job.passed_filters = False
    job.filter_reason = "not open to India (LLM): Remote - USA / Canada"

    again = store_job(session, raw(location="Remote"), StoreStats())
    assert again.passed_filters is False
    assert again.filter_reason == "not open to India (LLM): Remote - USA / Canada"
    assert again.india_eligible is False


def test_filtered_jobs_keep_reason(session):  # noqa: F811
    job = store_job(session, raw(location="Remote (US)"), StoreStats())
    assert job.passed_filters is False
    assert job.filter_reason == "remote, but restricted to other regions"
    assert session.scalar(select(Company).where(Company.name == "Zeta Test Co")) is not None
    assert session.get(Job, job.id).india_eligible is False
