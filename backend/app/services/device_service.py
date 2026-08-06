"""
Playback device pairing: Chromecast-style short-code linking of a physical
player machine to a venue account. One `DeviceLink` row per physical device
for its whole lifetime (see models.py docstring) -- registering an
already-known token just refreshes it rather than minting a new row.
"""
import secrets
import string
import time
from collections import defaultdict
from datetime import timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.models import DeviceLink, Venue, _utcnow

PAIRING_CODE_TTL = timedelta(minutes=10)

# In-process (not Redis-backed -- fine at this scale, see implementation plan)
# guard against an authenticated owner brute-forcing another venue's
# in-progress pairing code.
MAX_CLAIM_ATTEMPTS = 10
CLAIM_ATTEMPT_WINDOW_SECONDS = 600
_failed_claim_attempts: dict[int, list[float]] = defaultdict(list)


def _generate_pairing_code() -> str:
    return "".join(secrets.choice(string.digits) for _ in range(6))


async def _venue_summary(db: AsyncSession, venue_id: Optional[int]) -> dict:
    """Small standalone lookup rather than touching DeviceLink.venue directly --
    that relationship isn't eager-loaded, and lazy-loading it here would hit
    async SQLAlchemy's "MissingGreenlet" trap."""
    if venue_id is None:
        return {"venue_slug": None, "venue_name": None}
    result = await db.execute(select(Venue).where(Venue.id == venue_id))
    venue = result.scalars().first()
    if not venue:
        return {"venue_slug": None, "venue_name": None}
    return {"venue_slug": venue.slug, "venue_name": venue.name}


async def register_or_refresh_device(db: AsyncSession, device_token: Optional[str]) -> DeviceLink:
    device = None
    if device_token:
        result = await db.execute(select(DeviceLink).where(DeviceLink.device_token == device_token))
        device = result.scalars().first()

    now = _utcnow()

    if device:
        device.last_seen_at = now
        if device.venue_id is None:
            # Still unclaimed -- keep it pairable, but don't mint a new code out
            # from under the user just because the page polled again; only
            # refresh when the current one is missing/expired.
            if not device.pairing_code or not device.pairing_code_expires_at or device.pairing_code_expires_at <= now:
                device.pairing_code = _generate_pairing_code()
                device.pairing_code_expires_at = now + PAIRING_CODE_TTL
        await db.commit()
        await db.refresh(device)
        return device

    new_device = DeviceLink(
        device_token=secrets.token_urlsafe(32),
        pairing_code=_generate_pairing_code(),
        pairing_code_expires_at=now + PAIRING_CODE_TTL,
        last_seen_at=now,
    )
    db.add(new_device)
    await db.commit()
    await db.refresh(new_device)
    return new_device


async def get_device_by_token(db: AsyncSession, device_token: str) -> Optional[DeviceLink]:
    result = await db.execute(select(DeviceLink).where(DeviceLink.device_token == device_token))
    return result.scalars().first()


def _rate_limited(venue_id: int) -> bool:
    now = time.time()
    attempts = _failed_claim_attempts[venue_id]
    attempts[:] = [t for t in attempts if now - t < CLAIM_ATTEMPT_WINDOW_SECONDS]
    return len(attempts) >= MAX_CLAIM_ATTEMPTS


def _record_failed_attempt(venue_id: int) -> None:
    _failed_claim_attempts[venue_id].append(time.time())


async def claim_device(db: AsyncSession, venue: Venue, pairing_code: str) -> DeviceLink:
    """Raises PermissionError (rate-limited) or ValueError (bad/expired code)."""
    if _rate_limited(venue.id):
        raise PermissionError("Too many failed pairing attempts. Wait a few minutes and try again.")

    now = _utcnow()
    result = await db.execute(
        select(DeviceLink).where(
            DeviceLink.pairing_code == pairing_code,
            DeviceLink.venue_id.is_(None),
        )
    )
    device = result.scalars().first()

    if not device or not device.pairing_code_expires_at or device.pairing_code_expires_at <= now:
        _record_failed_attempt(venue.id)
        raise ValueError("Invalid or expired pairing code.")

    device.venue_id = venue.id
    device.claimed_at = now
    device.pairing_code = None
    device.pairing_code_expires_at = None
    await db.commit()
    await db.refresh(device)
    return device


async def list_devices(db: AsyncSession, venue: Venue) -> list[DeviceLink]:
    result = await db.execute(
        select(DeviceLink).where(DeviceLink.venue_id == venue.id).order_by(DeviceLink.created_at.asc())
    )
    return list(result.scalars().all())


async def unlink_device(db: AsyncSession, venue: Venue, device_id: int) -> bool:
    result = await db.execute(
        select(DeviceLink).where(DeviceLink.id == device_id, DeviceLink.venue_id == venue.id)
    )
    device = result.scalars().first()
    if not device:
        return False
    now = _utcnow()
    device.venue_id = None
    device.claimed_at = None
    device.pairing_code = _generate_pairing_code()
    device.pairing_code_expires_at = now + PAIRING_CODE_TTL
    await db.commit()
    return True
