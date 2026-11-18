import re
from datetime import UTC, datetime


def work_mode(value: object) -> str:
    """Map ATS workplace labels (Remote / Hybrid / OnSite / on-site / In Office) to ours."""
    if not isinstance(value, str):
        return "unknown"
    v = re.sub(r"[\s_-]", "", value.lower())
    if "remote" in v:
        return "remote"
    if "hybrid" in v:
        return "hybrid"
    if v in ("onsite", "inoffice", "inperson", "office"):
        return "onsite"
    return "unknown"


def mode_from_location(location: str, default: str = "unknown") -> str:
    loc = location.lower()
    if "remote" in loc:
        return "remote"
    if "hybrid" in loc:
        return "hybrid"
    return default


def iso_date(value: object) -> str:
    """ISO string or epoch-ms → YYYY-MM-DD ('' if unknown)."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, UTC).date().isoformat()
    if isinstance(value, str) and re.match(r"\d{4}-\d{2}-\d{2}", value):
        return value[:10]
    return ""
