import pytest

from app.models import RemoteType
from app.normalize.location import classify_location, hiring_band_excludes_india
from app.normalize.salary import parse_salary
from app.normalize.text import html_to_text, normalize_name

USD = 88.0


@pytest.mark.parametrize(
    ("text", "currency", "low", "high"),
    [
        ("$130K - $160K", "USD", 130_000 * USD, 160_000 * USD),
        ("$170k to $230k Base + Equity", "USD", 170_000 * USD, 230_000 * USD),
        ("€80,000 – €100,000", "EUR", 80_000 * 95, 100_000 * 95),
        ("₹30L - ₹50L", "INR", 3_000_000, 5_000_000),
        ("30-50 LPA", "INR", 3_000_000, 5_000_000),
        ("₹45,00,000 - ₹60,00,000", "INR", 4_500_000, 6_000_000),  # Indian digit grouping
        ("$60/hr contract", "USD", 60 * 2080 * USD, 60 * 2080 * USD),
        ("$8,000 per month", "USD", 96_000 * USD, 96_000 * USD),
        ("USD 120000 - 150000", "USD", 120_000 * USD, 150_000 * USD),
    ],
)
def test_parse_salary(text, currency, low, high):
    salary = parse_salary(text)
    assert salary is not None
    assert salary.currency == currency
    assert salary.min_inr == pytest.approx(low, rel=0.01)
    assert salary.max_inr == pytest.approx(high, rel=0.01)


def test_bare_k_range_needs_default_currency():
    assert parse_salary("70K-80K") is None
    assert parse_salary("70K-80K", default_currency="USD").max_inr == 80_000 * USD


@pytest.mark.parametrize(
    "text", ["Team of 40 engineers", "We have 3 offices", "hrs 40 per week", "Workers 2,000"]
)
def test_non_salary_numbers_are_ignored(text):
    assert parse_salary(text) is None


INDIA = (RemoteType.REMOTE_INDIA, True)
GLOBAL = (RemoteType.REMOTE_GLOBAL, True)
RESTRICTED = (RemoteType.REMOTE_RESTRICTED, False)
UNSPECIFIED = (RemoteType.REMOTE_UNSPECIFIED, None)


@pytest.mark.parametrize(
    ("location", "workplace", "expected"),
    [
        # Structured sources (strict): any named place other than India narrows the job.
        ("Remote (IN)", None, INDIA),
        ("Remote (US; CA)", None, RESTRICTED),
        ("Remote (New York, NY, US; Bengaluru, KA, IN)", None, INDIA),
        ("Worldwide", "remote", GLOBAL),
        ("USA Only", "remote", RESTRICTED),
        ("Seoul", "remote", RESTRICTED),
        ("United States", "remote", RESTRICTED),
        ("Madrid / Sofia / Berlin", "remote", RESTRICTED),
        ("Remote", None, UNSPECIFIED),
        (None, "remote", UNSPECIFIED),
        ("Remote - APAC", None, GLOBAL),
        ("Espoo", "hybrid", (RemoteType.HYBRID, False)),
        ("Long Beach, California", None, (RemoteType.ONSITE, False)),
        ("Bengaluru", "onsite", (RemoteType.ONSITE, False)),
        ("Remote", "hybrid", (RemoteType.HYBRID, False)),  # explicit workplace wins
        (None, None, (RemoteType.UNKNOWN, None)),
    ],
)
def test_classify_structured_location(location, workplace, expected):
    assert classify_location(location, workplace=workplace) == expected


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        # Free-text HN headers: only known region words narrow the job.
        ("REMOTE (Worldwide)", GLOBAL),
        ("REMOTE (US Timezones)", UNSPECIFIED),
        ("REMOTE (AMER or EMEA time zones)", UNSPECIFIED),
        ("REMOTE (Some crossover w/ PST required)", UNSPECIFIED),
        ("REMOTE (all remote)", UNSPECIFIED),
        ("REMOTE (US or Canada)", RESTRICTED),
        ("Remote but Boston based only", RESTRICTED),
        ("Full Time, Remote India", INDIA),
        ("ONSITE", (RemoteType.ONSITE, False)),
        ("NYC, Hybrid", (RemoteType.HYBRID, False)),
    ],
)
def test_classify_free_text_location(location, expected):
    assert classify_location(location, strict=False) == expected


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("You must be based in the US.", RESTRICTED),
        ("We hire anywhere in the world.", GLOBAL),
        ("Our team spans Europe and India.", INDIA),
        # Company boilerplate is not a hiring policy.
        ("We are a global leader with international customers.", UNSPECIFIED),
    ],
)
def test_description_decides_when_location_is_silent(description, expected):
    assert classify_location("Remote", description) == expected


@pytest.mark.parametrize(
    ("text", "excludes"),
    [
        ("Hiring GMT-8 to GMT+2", True),
        ("Remote (UTC-3 to UTC+3)", True),
        ("between UTC-5 and UTC+1", True),
        ("UTC+4 to UTC+9", False),
        ("GMT to GMT+5", False),  # within an hour of IST
        ("UTC+05:30 – UTC+08:00", False),
        ("US hours, 9-5 EST", False),  # overlap requirement, not a band
    ],
)
def test_hiring_band(text, excludes):
    assert hiring_band_excludes_india(text) is excludes


def test_hiring_band_in_free_text_location_restricts():
    location = "REMOTE (all remote) / Hiring GMT-8 to GMT+2"
    assert classify_location(location, strict=False) == RESTRICTED


def test_hiring_band_in_description_restricts():
    assert classify_location("Remote", "We hire between UTC-8 and UTC+1.") == RESTRICTED


def test_title_naming_india_wins_over_location():
    assert classify_location("Remote (US)", title="Forward Deployed Engineer - India") == INDIA


def test_html_to_text_handles_double_escaped_greenhouse_html():
    assert html_to_text("&lt;p&gt;Hello &amp;amp; welcome&lt;/p&gt;&lt;p&gt;Bye&lt;/p&gt;") == (
        "Hello & welcome\nBye"
    )


def test_normalize_name_ignores_suffixes():
    assert normalize_name("Acme AI, Inc.") == normalize_name("acme") == "acme"
