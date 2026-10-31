from datetime import UTC, datetime, timedelta

import pytest

from app.filters import filter_reason, is_target_role
from app.models import Job, RemoteType


@pytest.mark.parametrize(
    "title",
    [
        "AI Engineer",
        "Senior LLM Engineer",
        "Applied AI Engineer - Agents",
        "Agent Automation Engineer",
        "Senior Automation Engineer",
        "AI QA / Evals Engineer",
        "SDET",
        "Staff Software Engineer, Test Automation",
        "Forward Deployed Engineer (AI)",
        "Machine Learning Engineer",
        "Robotic Process Automation (RPA) Developer",
        "Software Engineer, AI Platform",
        # HN posts list several roles; one target role is enough.
        "Technical CSMs, Product Managers, AI Research Engineers",
    ],
)
def test_target_roles(title):
    assert is_target_role(title)


@pytest.mark.parametrize(
    "title",
    [
        "Product Engineer",
        "Senior Frontend Engineer",
        "AI Trainer - Video Annotation",
        "Engineering Manager, AI Platform",
        "Head of AI",
        "AI Sales Engineer Intern",
        "Marketing Automation Specialist",
        "Account Executive",
        "Senior Mechanical Test Engineer",
        "Engineering Technician 4, Quality Assurance",
        "Technical Product Lead AI Finance App",
        "Robotics Engineer, Autonomy",
        "Technical CSMs, Product Managers, AI Research",
    ],
)
def test_non_target_roles(title):
    assert not is_target_role(title)


def make_job(**overrides) -> Job:
    values = {"title": "AI Engineer", "remote_type": RemoteType.REMOTE_GLOBAL, "salary_max_inr": None,
                  "posted_at": datetime.now(UTC) - timedelta(days=3)}
    return Job(**{**values, **overrides})


def test_passing_job_has_no_reason():
    assert filter_reason(make_job()) is None


def test_unknown_salary_and_unspecified_region_still_pass():
    assert filter_reason(make_job(remote_type=RemoteType.REMOTE_UNSPECIFIED)) is None


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"title": "Product Designer"}, "role not targeted"),
        ({"remote_type": RemoteType.REMOTE_RESTRICTED}, "remote, but restricted to other regions"),
        ({"remote_type": RemoteType.ONSITE}, "not remote (onsite)"),
        ({"posted_at": datetime.now(UTC) - timedelta(days=90)}, "posted over 60 days ago"),
    ],
)
def test_filter_reasons(overrides, reason):
    assert filter_reason(make_job(**overrides)) == reason


def test_salary_is_not_a_shared_filter():
    # Each user sets their own minimum; low-paying jobs stay available to everyone.
    assert filter_reason(make_job(salary_max_inr=1_000_000)) is None
