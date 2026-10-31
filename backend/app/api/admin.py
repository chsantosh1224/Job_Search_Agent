"""Admin: users, their AI usage today, and disabling accounts."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, func, select

from app.api.auth import AdminDep, require_admin
from app.api.deps import SessionDep
from app.config import get_settings
from app.models import JobMatch, LLMUsage, Resume, User
from app.usage import calls_today, today

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class UserUpdate(BaseModel):
    is_active: bool


@router.get("/users")
def list_users(session: SessionDep) -> dict:
    day = today()
    ranked = (select(func.count()).select_from(JobMatch)
              .join(Resume, Resume.id == JobMatch.resume_id)
              .where(Resume.user_id == User.id, Resume.is_active.is_(True),
                     JobMatch.tier.is_not(None))
              .scalar_subquery())
    has_resume = select(Resume.id).where(Resume.user_id == User.id).exists()
    rows = session.execute(
        select(User, has_resume, ranked, LLMUsage)
        .outerjoin(LLMUsage, and_(LLMUsage.user_id == User.id, LLMUsage.day == day))
        .order_by(User.created_at.desc())
    ).all()
    settings = get_settings()
    return {
        "calls_today": calls_today(session, day),
        "daily_cap": settings.llm_daily_cap,
        "user_rank_limit": settings.user_daily_rank_limit,
        "user_brief_limit": settings.user_daily_brief_limit,
        "users": [
            {"id": u.id, "email": u.email, "name": u.name, "is_admin": u.is_admin,
             "is_active": u.is_active, "created_at": u.created_at,
             "last_login_at": u.last_login_at, "has_resume": resume, "matches": matches,
             "calls_today": usage.calls if usage else 0,
             "ranked_today": usage.ranked if usage else 0,
             "briefs_today": usage.briefs if usage else 0}
            for u, resume, matches, usage in rows
        ],
    }


@router.put("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, admin: AdminDep, session: SessionDep) -> dict:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if user.id == admin.id and not body.is_active:
        raise HTTPException(400, "You cannot disable your own account")
    user.is_active = body.is_active
    return {"id": user.id, "is_active": user.is_active}
