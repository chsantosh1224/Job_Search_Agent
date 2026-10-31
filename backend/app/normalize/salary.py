"""Parse free-text salary ranges and convert them to annual INR."""

import re
from dataclasses import dataclass

from app.config import get_settings

HOURS_PER_YEAR = 2080

_CURRENCY_MARKERS = {
    "us$": "USD", "usd": "USD", "$": "USD",
    "€": "EUR", "eur": "EUR",
    "£": "GBP", "gbp": "GBP",
    "₹": "INR", "inr": "INR", "rs.": "INR", "rs": "INR",
}
_CUR = r"(?:\bUS\$|\bUSD\b|\bEUR\b|\bGBP\b|\bINR\b|\bRs\.?|[$€£₹])"
# Longest alternatives first so "LPA" is not read as "L" + "PA".
_SUFFIX = r"(?:lakhs?|lacs?|lpa|l|crores?|cr|k|m)(?![a-z])"


_GROUPED = r"\d{1,2}(?:,\d{2})+,\d{3}|\d{1,3}(?:[,.]\d{3})+"  # Indian 45,00,000 or 4,500,000


def _amount_group(n: int) -> str:
    return rf"(?P<a{n}>{_GROUPED}|\d+(?:\.\d+)?)\s*(?P<s{n}>{_SUFFIX})?"


_RANGE_RE = re.compile(
    rf"(?P<c1>{_CUR})?\s*{_amount_group(1)}\s*(?P<c2>{_CUR})?"
    rf"(?:\s*(?:-|–|—|to)\s*(?P<c3>{_CUR})?\s*{_amount_group(2)}\s*(?P<c4>{_CUR})?)?",
    re.IGNORECASE,
)
_HOURLY_RE = re.compile(r"(/\s*(hr|hour|h)\b|per hour|hourly|an hour)", re.IGNORECASE)
_MONTHLY_RE = re.compile(r"(/\s*(mo|month)\b|per month|monthly|a month)", re.IGNORECASE)

_MULTIPLIERS = {"k": 1e3, "m": 1e6, "l": 1e5, "lpa": 1e5, "lakh": 1e5, "lakhs": 1e5,
                "lac": 1e5, "lacs": 1e5, "cr": 1e7, "crore": 1e7, "crores": 1e7}


@dataclass
class Salary:
    raw: str
    currency: str
    min_inr: int | None
    max_inr: int | None


def to_inr(amount: float, currency: str) -> int | None:
    settings = get_settings()
    rates = {"INR": 1.0, "USD": settings.usd_to_inr, "EUR": settings.eur_to_inr,
             "GBP": settings.gbp_to_inr}
    rate = rates.get(currency.upper())
    return round(amount * rate) if rate else None


def annualize(amount: float, interval: str) -> float:
    return amount * {"hour": HOURS_PER_YEAR, "month": 12}.get(interval, 1)


def from_range(raw: str, low: float | None, high: float | None, currency: str | None,
               interval: str = "year") -> Salary | None:
    """Build a Salary from already-structured numbers (RemoteOK, Lever)."""
    if not currency or not (low or high):
        return None
    low, high = low or high, high or low
    return Salary(
        raw=raw,
        currency=currency.upper(),
        min_inr=to_inr(annualize(low, interval), currency),
        max_inr=to_inr(annualize(high, interval), currency),
    )


def _amount(number: str, suffix: str | None) -> float:
    if re.fullmatch(_GROUPED, number):
        number = re.sub(r"[,.]", "", number)
    return float(number) * _MULTIPLIERS.get((suffix or "").lower(), 1)


def parse_salary(text: str | None, default_currency: str | None = None) -> Salary | None:
    """Find the first salary-looking range in text.

    A match needs a currency marker or an Indian unit (L / LPA / Cr), unless a default currency
    is given and the amount has a unit (e.g. Remotive's bare "70K-80K", which is USD).
    """
    if not text:
        return None
    for match in _RANGE_RE.finditer(text):
        s1, s2 = match.group("s1"), match.group("s2")
        marker = next((match.group(g) for g in ("c1", "c2", "c3", "c4") if match.group(g)), None)
        currency = _CURRENCY_MARKERS[marker.lower()] if marker else None
        if currency is None and any(s and s.lower()[0] in "lc" for s in (s1, s2)):
            currency = "INR"
        if currency is None:
            if not default_currency or not (s1 or s2):
                continue
            currency = default_currency

        # "30-50 LPA": a unit written only after the second number applies to both.
        low = _amount(match.group("a1"), s1 or s2)
        high = _amount(match.group("a2"), s2 or s1) if match.group("a2") else low
        tail = text[match.end(): match.end() + 25]
        interval = ("hour" if _HOURLY_RE.search(tail)
                    else "month" if _MONTHLY_RE.search(tail) else "year")
        if annualize(high, interval) < 1000:  # "$5", "₹10": not a salary
            continue
        return from_range(match.group(0).strip(), low, high, currency, interval)
    return None
