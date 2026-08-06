"""
QR entry passes. Issuing one just mints an opaque token row -- no sensitive
data is encoded in the QR itself (PLAN.md section 8); the scanner endpoint
(access_service.scan_qr_pass) looks the token up server-side and re-runs the
access engine at scan time, so revoking/expiring a pass takes effect
immediately without needing to reissue anything.
"""
import secrets
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.models import QrPass, QrPassStatus, User, Venue


async def get_or_create_pass(db: AsyncSession, venue: Venue, user: User) -> QrPass:
    result = await db.execute(
        select(QrPass).where(
            QrPass.user_id == user.id,
            QrPass.venue_id == venue.id,
            QrPass.status == QrPassStatus.ACTIVE,
        )
    )
    existing = result.scalars().first()
    if existing:
        return existing

    qr_pass = QrPass(user_id=user.id, venue_id=venue.id, token=secrets.token_urlsafe(24))
    db.add(qr_pass)
    await db.commit()
    await db.refresh(qr_pass)
    return qr_pass


async def revoke_pass(db: AsyncSession, venue_id: int, token: str) -> bool:
    result = await db.execute(select(QrPass).where(QrPass.token == token, QrPass.venue_id == venue_id))
    qr_pass = result.scalars().first()
    if not qr_pass:
        return False
    qr_pass.status = QrPassStatus.REVOKED
    await db.commit()
    return True
