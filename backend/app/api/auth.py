"""Google sign-in (OpenID Connect, server-side code flow) and session cookies.

Flow: /api/auth/google/login stores a one-time state + nonce in a short-lived signed cookie and
redirects to Google. Google redirects back to /api/auth/google/callback with a code, which is
exchanged for an ID token; the token is verified against Google's published keys, audience,
issuer and nonce before the user is signed in.
"""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.api.deps import SessionDep
from app.config import Settings, get_settings
from app.models import User
from app.users import sign_in

SettingsDep = Annotated[Settings, Depends(get_settings)]
COOKIE_NAME = "jobagent_session"
STATE_COOKIE = "jobagent_oauth"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
_google_keys = jwt.PyJWKClient("https://www.googleapis.com/oauth2/v3/certs", cache_keys=True)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _require_secret(settings: Settings) -> None:
    if not settings.jwt_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "JWT_SECRET is not configured")


def start_session(response: Response, user: User, settings: Settings) -> None:
    _require_secret(settings)
    expires = datetime.now(UTC) + timedelta(days=settings.session_days)
    token = jwt.encode({"sub": str(user.id), "exp": expires}, settings.jwt_secret,
                       algorithm="HS256")
    # Lax, not strict: the first request after Google's redirect is a cross-site navigation.
    response.set_cookie(COOKIE_NAME, token, httponly=True, secure=settings.cookie_secure,
                        samesite="lax", max_age=settings.session_days * 86400, path="/")


def _safe_next(path: str | None) -> str:
    """Only same-site relative paths, so the login cannot redirect to another site."""
    if path and path.startswith("/") and not path.startswith("//") and "\\" not in path:
        return path
    return "/jobs"


@router.get("/config")
def auth_config(settings: SettingsDep) -> dict:
    return {"google": bool(settings.google_client_id), "dev_login": settings.dev_login}


@router.get("/google/login")
def google_login(settings: SettingsDep, next: str | None = None) -> RedirectResponse:
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Google sign-in is not set up")
    _require_secret(settings)
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": f"{settings.public_url.rstrip('/')}/api/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "prompt": "select_account",
    }
    response = RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}", status_code=302)
    flow = jwt.encode({"state": state, "nonce": nonce, "next": _safe_next(next),
                       "exp": datetime.now(UTC) + timedelta(minutes=10)},
                      settings.jwt_secret, algorithm="HS256")
    response.set_cookie(STATE_COOKIE, flow, httponly=True, secure=settings.cookie_secure,
                        samesite="lax", max_age=600, path="/api/auth")
    return response


def verify_google_id_token(id_token: str, client_id: str) -> dict:
    key = _google_keys.get_signing_key_from_jwt(id_token)
    claims = jwt.decode(id_token, key.key, algorithms=["RS256"], audience=client_id)
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise jwt.InvalidIssuerError("unexpected issuer")
    return claims


@router.get("/google/callback")
def google_callback(request: Request, session: SessionDep, settings: SettingsDep,
                    code: str | None = None, state: str | None = None,
                    error: str | None = None) -> RedirectResponse:
    def fail(reason: str) -> RedirectResponse:
        response = RedirectResponse(f"/login?error={reason}", status_code=302)
        response.delete_cookie(STATE_COOKIE, path="/api/auth")
        return response

    if error or not code or not state:
        return fail("cancelled")
    try:
        flow = jwt.decode(request.cookies.get(STATE_COOKIE, ""), settings.jwt_secret,
                          algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return fail("expired")
    if not secrets.compare_digest(flow["state"], state):
        return fail("state")

    try:
        token = httpx.post(GOOGLE_TOKEN_URL, timeout=20, data={
            "code": code, "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": f"{settings.public_url.rstrip('/')}/api/auth/google/callback",
            "grant_type": "authorization_code",
        })
        token.raise_for_status()
        claims = verify_google_id_token(token.json()["id_token"], settings.google_client_id)
    except (httpx.HTTPError, KeyError, jwt.PyJWTError):
        return fail("google")
    if claims.get("nonce") != flow["nonce"] or not claims.get("email_verified"):
        return fail("unverified")

    user = sign_in(session, email=claims["email"], name=claims.get("name", ""),
                   google_sub=claims["sub"])
    if not user.is_active:
        return fail("disabled")
    response = RedirectResponse(flow["next"], status_code=302)
    response.delete_cookie(STATE_COOKIE, path="/api/auth")
    start_session(response, user, settings)
    return response


class DevLogin(BaseModel):
    email: str
    name: str = ""


@router.post("/dev-login", status_code=status.HTTP_204_NO_CONTENT)
def dev_login(body: DevLogin, request: Request, response: Response, session: SessionDep,
              settings: SettingsDep) -> None:
    """Local testing without Google. Off unless DEV_LOGIN=true, and only from this machine."""
    client = request.client.host if request.client else ""
    if not settings.dev_login or client not in ("127.0.0.1", "::1", "testclient"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    user = sign_in(session, email=body.email, name=body.name or body.email.split("@")[0],
                   google_sub=None)
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")
    start_session(response, user, settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def current_user(request: Request, session: SessionDep, settings: SettingsDep) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token or not settings.jwt_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        user = session.get(User, int(claims["sub"]))
    except (jwt.InvalidTokenError, KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired") from exc
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")
    return user


def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admins only")
    return user


# FastAPI caches dependencies per request, so endpoints using UserDep and SessionDep get the
# same database session the user was loaded with.
UserDep = Annotated[User, Depends(current_user)]
AdminDep = Annotated[User, Depends(require_admin)]
