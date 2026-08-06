"""
Venue owner authentication: password hashing, signed session cookies, and the
`get_current_venue` dependency used to gate every /api/dashboard/* route.

Deliberately simple for v1: bcrypt for hashing, an itsdangerous signed cookie
for sessions (no JWT library, no server-side session store needed). No
password reset / email verification -- out of scope, see the implementation
plan.
"""
import re
import secrets
import string
from typing import Optional

import bcrypt
from fastapi import Cookie, Depends, HTTPException, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.config import settings
from backend.app.database import get_db
from backend.app.models import Venue

SESSION_COOKIE_NAME = "venue_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days

_serializer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="venue-session")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed/legacy hash -- treat as a failed login, not a server error.
        return False


def create_session_token(venue_id: int) -> str:
    return _serializer.dumps({"venue_id": venue_id})


def set_session_cookie(response: Response, venue_id: int) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=create_session_token(venue_id),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=bool(settings.PUBLIC_ORIGIN),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")


def verify_session_token(token: str) -> Optional[int]:
    """Returns the venue_id encoded in a valid, unexpired session token, or
    None. Shared by the HTTP cookie dependency below and the WebSocket route
    (which reads the same cookie but can't use a FastAPI HTTP dependency)."""
    try:
        payload = _serializer.loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    return payload.get("venue_id")


async def get_venue_by_id(db: AsyncSession, venue_id: int) -> Optional[Venue]:
    result = await db.execute(select(Venue).where(Venue.id == venue_id))
    return result.scalars().first()


async def get_current_venue(
    venue_session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> Venue:
    if not venue_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
    venue_id = verify_session_token(venue_session)
    if venue_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid.")

    venue = await get_venue_by_id(db, venue_id)
    if not venue:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Venue account no longer exists.")
    return venue


_SLUG_SAFE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    base = _SLUG_SAFE.sub("-", name.strip().lower()).strip("-")
    return base or "venue"


async def generate_unique_slug(db: AsyncSession, name: str) -> str:
    """Slug + short random suffix, retried on the rare collision."""
    base = slugify(name)
    for _ in range(5):
        suffix = "".join(secrets.choice(string.digits) for _ in range(4))
        candidate = f"{base}-{suffix}"
        result = await db.execute(select(Venue.id).where(Venue.slug == candidate))
        if result.scalars().first() is None:
            return candidate
    # Astronomically unlikely to ever hit this, but never loop forever.
    return f"{base}-{secrets.token_hex(6)}"
