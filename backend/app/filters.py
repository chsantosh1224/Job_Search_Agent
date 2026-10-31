"""Hard filters: cheap rules applied before any embedding or LLM work."""

import re
from datetime import UTC, datetime, timedelta

from app.config import get_settings
from app.models import Job, RemoteType

# Target families: AI / LLM / agents, automation, QA / evals.
_ROLE_FAMILY = re.compile(
    r"\b(ai|a\.i\.|ml|llms?|genai|gen ai|generative|machine learning|applied (ai|ml)|agents?|"
    r"agentic|automation|rpa|qa|quality|sdet|test|tests|testing|evals?|evaluation|"
    r"forward[- ]deployed|prompt|intelligence)\b",
    re.IGNORECASE,
)
_ENGINEERING = re.compile(
    r"\b(engineers?|engineering|developers?|sdet|architects?|scientists?|specialists?|leads?|"
    r"testers?|analysts?)\b",
    re.IGNORECASE,
)
_EXCLUDED = re.compile(
    r"\b(intern|internship|sales|account executive|marketing|recruit\w*|designer|counsel|attorney|"
    r"director|vp|vice president|head of|chief|manager|trainer|annotat\w*|tutor|labell?ing|"
    r"writer|evaluator|rater|contributor|data entry|product (lead|owner)|"
    # Hardware / physical-world roles that share words like "test" and "quality".
    r"mechanical|electrical|hardware|manufacturing|technician|civil|structural|chemical|"
    # "robotics", not "robotic": Robotic Process Automation (RPA) roles are a target.
    r"propulsion|avionics|mechatronics|robotics)s?\b",
    re.IGNORECASE,
)
_ROLE_LIST_SEPARATOR = re.compile(r",|;|\s/\s|\band\b")
# Filter reasons starting with this were set by the LLM ranking step, not by these rules.
LLM_INDIA_PREFIX = "not open to India (LLM)"

ACCEPTED_REMOTE ={RemoteType.REMOTE_GLOBAL, RemoteType.REMOTE_INDIA, RemoteType.REMOTE_UNSPECIFIED}


def _matches(title: str) -> bool:
    return bool(
        _ROLE_FAMILY.search(title) and _ENGINEERING.search(title) and not _EXCLUDED.search(title)
    )


def is_target_role(title: str) -> bool:
    """True if the title, or any role in a list of roles (common in HN posts), is a target.

    The whole title is tried first so "Software Engineer, AI Platform" counts as one role.
    """
    if _matches(title):
        return True
    roles = _ROLE_LIST_SEPARATOR.split(title)
    return len(roles) > 1 and any(_matches(role) for role in roles)


def filter_reason(job: Job, now: datetime | None = None) -> str | None:
    """Why a job is filtered out for everyone, or None if it passes.

    Salary is not a shared filter: each user sets their own minimum and search range.
    """
    settings = get_settings()
    now = now or datetime.now(UTC)
    if not is_target_role(job.title):
        return "role not targeted"
    if job.remote_type == RemoteType.REMOTE_RESTRICTED:
        return "remote, but restricted to other regions"
    if job.remote_type not in ACCEPTED_REMOTE:
        return f"not remote ({job.remote_type.value})"
    if job.posted_at and now - job.posted_at > timedelta(days=settings.max_job_age_days):
        return f"posted over {settings.max_job_age_days} days ago"
    return None
