"""User accounts: sign-in upsert and admin bootstrap."""

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Application, Resume, User


def sign_in(session: Session, *, email: str, name: str, google_sub: str | None) -> User:
    """Find or create the user for a verified sign-in, and refresh their details."""
    email = email.strip().lower()
    user = None
    if google_sub:
        user = session.scalar(select(User).where(User.google_sub == google_sub))
    if user is None:
        # An account created before its first Google sign-in (the bootstrapped admin).
        user = session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, name=name)
        session.add(user)
    if google_sub and user.google_sub is None:
        user.google_sub = google_sub
    user.email = email
    user.name = user.name or name
    if email in get_settings().admin_email_set:
        user.is_admin = True
    user.last_login_at = datetime.now(UTC)
    session.flush()
    return user


def primary_admin(session: Session) -> User | None:
    """The admin whose resume and labels the evals use (the first admin account)."""
    return session.scalar(select(User).where(User.is_admin.is_(True)).order_by(User.id))


def bootstrap_admin(session: Session, email: str) -> tuple[User, dict]:
    """Create the admin account and give it the data from the single-user version."""
    email = email.strip().lower()
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, name="", is_admin=True)
        session.add(user)
        session.flush()
    user.is_admin = True
    claimed = {
        "resumes": session.execute(
            update(Resume).where(Resume.user_id.is_(None)).values(user_id=user.id)
        ).rowcount,
        "applications": session.execute(
            update(Application).where(Application.user_id.is_(None)).values(user_id=user.id)
        ).rowcount,
    }
    return user, claimed
