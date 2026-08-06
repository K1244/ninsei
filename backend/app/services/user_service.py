"""
Patron identity (see models.User's docstring): mints/refreshes a bearer
token and lets a patron set a display name/avatar. Same
register-or-refresh-by-token pattern device_service.register_or_refresh_device
already uses for playback devices -- just for people instead of machines.
"""
import secrets
from typing import Optional

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.config import AVATAR_KEYS
from backend.app.database import get_db
from backend.app.models import User


async def get_user_by_token(db: AsyncSession, token: Optional[str]) -> Optional[User]:
    if not token:
        return None
    result = await db.execute(select(User).where(User.token == token))
    return result.scalars().first()


async def identify_or_create(db: AsyncSession, token: Optional[str]) -> User:
    """Returns the existing patron for `token` if it's still valid, otherwise
    mints a brand new one -- mirrors device_service's "unknown/missing token
    just gets a fresh identity" behavior rather than erroring."""
    user = await get_user_by_token(db, token)
    if user:
        return user
    user = User(token=secrets.token_urlsafe(32))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_profile(db: AsyncSession, user: User, display_name: Optional[str], avatar: Optional[str]) -> User:
    if display_name is not None:
        user.display_name = display_name.strip()[:80] or None
    if avatar is not None:
        avatar = avatar.strip()
        # Empty string clears the avatar back to "unset"; anything else must
        # be one of config.AVATAR_OPTIONS' keys (see GET /api/users/avatar-options)
        # rather than an arbitrary string, since it's rendered straight back
        # as a sprite file path client-side.
        if avatar and avatar not in AVATAR_KEYS:
            raise ValueError(f"Unknown avatar '{avatar}'.")
        user.avatar = avatar or None
    await db.commit()
    await db.refresh(user)
    return user


async def get_optional_user(
    x_user_token: Optional[str] = Header(default=None, alias="X-User-Token"),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """FastAPI dependency: resolves the calling patron from the X-User-Token
    header if present and valid, or None for anonymous/unidentified browsing.
    Deliberately never raises -- most of the guest-facing surface (viewing a
    venue, observing) works fine with no identity at all; see access_service.py
    for what changes once someone *does* have one."""
    return await get_user_by_token(db, x_user_token)


async def require_user(
    x_user_token: Optional[str] = Header(default=None, alias="X-User-Token"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """FastAPI dependency for endpoints that actually mutate patron state
    (joining a membership, requesting access, ...): lazily creates an
    identity from whatever token is sent (even none) rather than forcing a
    separate /api/users/identify round-trip first -- matches the plan's
    "guest mode / quick start" framing. The response always echoes the
    User's token back (see schemas.UserResponse-shaped fields on call sites)
    so the client can persist a freshly minted one."""
    return await identify_or_create(db, x_user_token)
