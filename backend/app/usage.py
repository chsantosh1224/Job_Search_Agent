"""Daily LLM usage per user, for the per-user and overall limits. Days follow India time,
matching the daily run."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import LLMUsage

IST = ZoneInfo("Asia/Kolkata")


def today() -> date:
    return datetime.now(UTC).astimezone(IST).date()


def usage_row(session: Session, user_id: int | None, day: date | None = None) -> LLMUsage:
    day = day or today()
    owner = LLMUsage.user_id.is_(None) if user_id is None else LLMUsage.user_id == user_id
    row = session.scalar(select(LLMUsage).where(LLMUsage.day == day, owner))
    if row is None:
        row = LLMUsage(day=day, user_id=user_id, calls=0, ranked=0, briefs=0)
        session.add(row)
        session.flush()
    return row


def calls_today(session: Session, day: date | None = None) -> int:
    return session.scalar(
        select(func.coalesce(func.sum(LLMUsage.calls), 0)).where(LLMUsage.day == (day or today()))
    )


def record(session: Session, user_id: int | None, calls: int, ranked: int = 0,
           briefs: int = 0) -> None:
    row = usage_row(session, user_id)
    row.calls += calls
    row.ranked += ranked
    row.briefs += briefs
