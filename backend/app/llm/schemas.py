"""Validated shapes of LLM replies. Validators absorb common free-model quirks
(tier as "2" or 0, scores out of range, a string where a list belongs)."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [str(item) for item in value if str(item).strip()]


class RankResult(BaseModel):
    tier: int | None = Field(description="1, 2, 3, or null when the job is not a fit")
    fit_score: int
    reasons: list[str] = []
    gaps: list[str] = []
    india_eligibility: Literal["yes", "no", "unclear"] = "unclear"
    eligibility_evidence: str | None = None

    @field_validator("tier", mode="before")
    @classmethod
    def _tier(cls, value: object) -> int | None:
        try:
            tier = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return tier if tier in (1, 2, 3) else None

    @field_validator("fit_score", mode="before")
    @classmethod
    def _score(cls, value: object) -> int:
        return max(0, min(100, int(float(value))))  # type: ignore[arg-type]

    @field_validator("reasons", "gaps", mode="before")
    @classmethod
    def _lists(cls, value: object) -> list[str]:
        return _as_list(value)[:4]

    @field_validator("india_eligibility", mode="before")
    @classmethod
    def _eligibility(cls, value: object) -> str:
        value = str(value or "").strip().lower()
        return value if value in ("yes", "no") else "unclear"


class Claim(BaseModel):
    claim: str
    supported: bool
    evidence: str | None = None

    @field_validator("supported", mode="before")
    @classmethod
    def _supported(cls, value: object) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in ("true", "yes", "supported")
        return bool(value)


class JudgeResult(BaseModel):
    claims: list[Claim]
    specificity: int
    usefulness: int
    comment: str = ""

    @field_validator("specificity", "usefulness", mode="before")
    @classmethod
    def _rating(cls, value: object) -> int:
        return max(1, min(5, round(float(value))))  # type: ignore[arg-type]

    @field_validator("claims", mode="before")
    @classmethod
    def _claims(cls, value: object) -> list:
        return [c for c in value or [] if isinstance(c, dict) and c.get("claim")]


class Person(BaseModel):
    name: str
    role: str | None = None


class ResearchBriefContent(BaseModel):
    # Core content is required; secondary fields default so one dropped key (a common free-model
    # slip) does not discard an otherwise good brief.
    company_summary: str
    stage_and_funding: str = "Not stated in the posting"
    people: list[Person] = []
    lead_project: str
    why_lead_project: str = ""
    talking_points: list[str]
    verify_before_reaching_out: list[str] = []

    @field_validator("talking_points", "verify_before_reaching_out", mode="before")
    @classmethod
    def _lists(cls, value: object) -> list[str]:
        return _as_list(value)[:4]

    @field_validator("people", mode="before")
    @classmethod
    def _people(cls, value: object) -> list:
        return [p for p in value or [] if isinstance(p, dict) and p.get("name")][:5]
