"""Classify where a job can be done from, and whether someone based in India can take it.

Inputs are the source's location (places only), its explicit workplace type when it has one, the
title and the description. For structured sources any named place other than India narrows a
remote job to that place; for free-text sources (HN headers) only known region words do.
When a remote job names no region, the description decides; if it is still unclear the job is
kept as "remote, unspecified" rather than dropped.
"""

import re

from app.models import RemoteType

_INDIA = re.compile(
    r"\b(india|indian|bangalore|bengaluru|hyderabad|pune|chennai|mumbai|delhi|gurgaon|gurugram|"
    r"noida|kolkata|ahmedabad|kochi)\b",
    re.IGNORECASE,
)
_GLOBAL = re.compile(
    r"\b(worldwide|anywhere|global(ly)?|international|apac|asia|asia[- ]pacific|"
    r"all locations|any location)\b",
    re.IGNORECASE,
)
# Descriptions say "global" about the company all the time, so only explicit phrases count.
_DESCRIPTION_GLOBAL = re.compile(
    r"(work from anywhere|anywhere in the world|\bworldwide\b|from any country|any time ?zone|"
    r"hire (globally|internationally|worldwide)|location[- ]independent|visa not required)",
    re.IGNORECASE,
)
_REGIONS = re.compile(
    r"\b(us|usa|u\.s\.a?\.?|united states|america|north america|namer|canada|can|uk|"
    r"united kingdom|england|london|europe|european union|eu|latam|latin america|germany|"
    r"france|spain|netherlands|poland|portugal|ireland|israel|brazil|mexico|argentina|colombia|"
    r"australia|new zealand|singapore|japan|korea|seoul|turkey|san francisco|sf|bay area|"
    r"new york|nyc|seattle|austin|boston|chicago|los angeles|toronto|berlin|amsterdam|paris)\b",
    re.IGNORECASE,
)
# Time-zone overlap is fine (the candidate works night / early-morning IST): not a region limit.
_TIMEZONE = re.compile(
    r"\b(us|u\.s\.|eu|europe(an)?|americas?|amer|emea|uk|pacific|eastern|central)\s*[-/]?\s*"
    r"(time\s*zones?|timezones?|tz|hours|business hours)\b|\b(est|edt|pst|pdt|cst|cet|gmt|utc)\b"
    r"(\s*[+±-]\s*\d+)?",
    re.IGNORECASE,
)
# A stated hiring band ("Hiring GMT-8 to GMT+2", "between UTC-5 and UTC+3") says where hires
# may live, unlike a required overlap ("US hours"), which the candidate can work.
_OFFSET = r"(?:gmt|utc)\s*(?P<{}>[+\-−]\s*\d{{1,2}}(?:[:.]\d{{2}})?)?"
_BAND = re.compile(
    _OFFSET.format("low") + r"\s*(?:to|-|–|—|and)\s*" + _OFFSET.format("high"), re.IGNORECASE
)
INDIA_UTC_OFFSET = 5.5
_BAND_TOLERANCE = 1.0  # an hour either side is workable
_CODES = re.compile(r"remote\s*\(([^)]*)\)", re.IGNORECASE)
_REMOTE = re.compile(r"\b(remote|distributed|work from home|wfh)\b", re.IGNORECASE)
_HYBRID = re.compile(r"\bhybrid\b", re.IGNORECASE)
_ONSITE = re.compile(r"\b(on-?site|in[- ]office|in[- ]person)\b", re.IGNORECASE)
# Words that say how, not where; whatever remains in a structured location is a place.
_NOT_PLACES = re.compile(
    r"\b(remote|fully|full|part|time|contract|contractor|permanent|work|from|home|wfh|"
    r"distributed|first|friendly|only|ok|or|and|the|in|to|of|preferred|possible)\b",
    re.IGNORECASE,
)
_DESCRIPTION_RESTRICTED = re.compile(
    r"(must (be|live|reside)( currently)? (based |located )?in (the )?(us|u\.s\.|usa|united states|"
    r"canada|uk|europe|eu)\b|(us|u\.s\.)[- ]based (only|candidates)|authorized to work in the "
    r"(us|u\.s\.|united states)|us citizens? only|only (hiring|accepting) (candidates )?(in|from) "
    r"(the )?(us|u\.s\.|usa|united states|canada|europe|uk))",
    re.IGNORECASE,
)


def _country_codes(location: str) -> list[str] | None:
    """YC style 'Remote (US; CA)' / 'Remote (Bengaluru, KA, IN)': ISO codes, one per entry.

    Only used when every entry ends in a two-letter code, so 'REMOTE (Worldwide)' is not read
    as a country.
    """
    match = _CODES.search(location)
    if not match:
        return None
    codes = [entry.split(",")[-1].strip() for entry in match.group(1).split(";")]
    return codes if codes and all(re.fullmatch(r"[A-Z]{2}", c) for c in codes) else None


def _offset_hours(value: str | None) -> float:
    if not value:
        return 0.0
    value = value.replace("−", "-").replace(" ", "")
    sign = -1 if value.startswith("-") else 1
    hours, _, minutes = value.lstrip("+-").replace(".", ":").partition(":")
    return sign * (int(hours) + int(minutes or 0) / 60)


def hiring_band_excludes_india(text: str) -> bool:
    for match in _BAND.finditer(text):
        low, high = sorted((_offset_hours(match.group("low")), _offset_hours(match.group("high"))))
        if not low - _BAND_TOLERANCE <= INDIA_UTC_OFFSET <= high + _BAND_TOLERANCE:
            return True
    return False


def _workplace(location: str) -> str | None:
    if _REMOTE.search(location):
        return "remote"
    if _HYBRID.search(location):
        return "hybrid"
    if _ONSITE.search(location) or location.strip():
        return "onsite"
    return None


def classify_location(
    location: str | None,
    description: str = "",
    workplace: str | None = None,
    title: str = "",
    strict: bool = True,
) -> tuple[RemoteType, bool | None]:
    """Return (remote type, India-eligible: True / False / None for unknown).

    workplace: the source's explicit "remote" / "hybrid" / "onsite", if it has one.
    strict: location is a clean place list (APIs) rather than free text (HN headers).
    """
    loc = _TIMEZONE.sub(" ", location or "")
    workplace = workplace or _workplace(loc)
    if workplace is None:
        return RemoteType.UNKNOWN, None
    if workplace == "hybrid":
        return RemoteType.HYBRID, False
    if workplace != "remote":
        return RemoteType.ONSITE, False

    if _INDIA.search(loc) or _INDIA.search(title):
        return RemoteType.REMOTE_INDIA, True
    if hiring_band_excludes_india(location or ""):
        return RemoteType.REMOTE_RESTRICTED, False
    codes = _country_codes(loc)
    if codes is not None:
        return (RemoteType.REMOTE_INDIA, True) if "IN" in codes else (
            RemoteType.REMOTE_RESTRICTED, False)
    if _GLOBAL.search(loc):
        return RemoteType.REMOTE_GLOBAL, True
    places = (re.sub(r"[^a-z]+", " ", _NOT_PLACES.sub(" ", loc).lower()).strip()
              if strict else "")
    if places or _REGIONS.search(loc):
        return RemoteType.REMOTE_RESTRICTED, False

    text = _TIMEZONE.sub(" ", description)
    if _INDIA.search(text):
        return RemoteType.REMOTE_INDIA, True
    if hiring_band_excludes_india(description) or _DESCRIPTION_RESTRICTED.search(text):
        return RemoteType.REMOTE_RESTRICTED, False
    if _DESCRIPTION_GLOBAL.search(text):
        return RemoteType.REMOTE_GLOBAL, True
    return RemoteType.REMOTE_UNSPECIFIED, None
