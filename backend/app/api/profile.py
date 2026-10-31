"""The signed-in user's profile: details, USD salary minimum, consent, resume, account deletion."""

import io
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from pypdf.errors import PdfReadError
from sqlalchemy import select

from app.api.auth import COOKIE_NAME, UserDep
from app.api.deps import SessionDep
from app.models import JobMatch, LLMUsage, User
from app.resume.ingest import get_active_resume, store_resume
from app.resume.parser import parse_resume

router = APIRouter(prefix="/api/me", tags=["profile"])

MAX_RESUME_BYTES = 5 * 1024 * 1024


class ProfileUpdate(BaseModel):
    name: Annotated[str, Field(max_length=255)]
    about: Annotated[str, Field(max_length=2000)] = ""
    # Annual base salary in US dollars.
    min_salary_usd: Annotated[int | None, Field(ge=0, le=2_000_000)] = None


def profile(session, user: User) -> dict:
    resume = get_active_resume(session, user.id)
    ranked = session.scalar(
        select(JobMatch.id).where(JobMatch.resume_id == resume.id, JobMatch.model.is_not(None))
        .limit(1)
    ) if resume else None
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "about": user.about,
        "min_salary_usd": user.min_salary_usd,
        "is_admin": user.is_admin,
        "consented": user.consented_at is not None,
        "resume": {"filename": resume.filename, "uploaded_at": resume.created_at,
                   "ready": resume.embedding is not None, "ranked": ranked is not None}
        if resume else None,
    }


@router.get("")
def get_me(user: UserDep, session: SessionDep) -> dict:
    return profile(session, user)


@router.put("")
def update_me(body: ProfileUpdate, user: UserDep, session: SessionDep) -> dict:
    user.name = body.name.strip()
    user.about = body.about.strip()
    user.min_salary_usd = body.min_salary_usd
    return profile(session, user)


@router.post("/consent")
def consent(user: UserDep, session: SessionDep) -> dict:
    user.consented_at = user.consented_at or datetime.now(UTC)
    return profile(session, user)


@router.post("/resume")
async def upload_resume(file: UploadFile, user: UserDep, session: SessionDep) -> dict:
    if user.consented_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Please agree to how your resume is used before uploading")
    data = await file.read(MAX_RESUME_BYTES + 1)
    if len(data) > MAX_RESUME_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Resume must be under 5 MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Please upload a PDF")
    try:
        parsed = parse_resume(io.BytesIO(data))
        store_resume(session, user.id, parsed, file.filename or "resume.pdf")
    except (PdfReadError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Could not read this PDF: {exc}") from exc
    session.flush()

    # Rank this user's jobs now rather than waiting for the next daily run.
    from app.pipeline import queue_run

    session.commit()  # the worker must see the resume
    queue_run("resume", user_id=user.id)
    return profile(session, user)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(user: UserDep, session: SessionDep, response: Response) -> None:
    """Delete the account with its resumes, rankings, briefs, tracker and usage records."""
    session.execute(LLMUsage.__table__.delete().where(LLMUsage.user_id == user.id))
    # Database cascades: resumes -> chunks, matches, briefs; applications; the user's runs.
    session.delete(user)
    response.delete_cookie(COOKIE_NAME, path="/")
