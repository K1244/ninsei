"""
Pro-only venue style rules: an owner defines a small tag list (e.g. "Metal",
"Hip-Hop") each marked preferred / premium_only / prohibited. No search
provider returns reliable genre metadata (see media_providers/), so the tag
is picked by the guest at request time rather than auto-detected -- see
guest_router.py's queue/add flow and check_style_for_add below.

Free venues ignore style rules entirely: check_style_for_add always returns
"allowed" for them, regardless of what's configured (rules only take effect
once/while the venue is Pro).
"""
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from backend.app.models import Venue, VenueStyle, StyleRule


async def list_venue_styles(db: AsyncSession, venue_id: int) -> List[VenueStyle]:
    result = await db.execute(
        select(VenueStyle).where(VenueStyle.venue_id == venue_id).order_by(VenueStyle.name.asc())
    )
    return list(result.scalars().all())


async def _find_style(db: AsyncSession, venue_id: int, name: str) -> Optional[VenueStyle]:
    result = await db.execute(
        select(VenueStyle).where(
            VenueStyle.venue_id == venue_id,
            func.lower(VenueStyle.name) == name.strip().lower(),
        )
    )
    return result.scalars().first()


async def upsert_style(db: AsyncSession, venue_id: int, name: str, rule: str) -> VenueStyle:
    try:
        rule_enum = StyleRule(rule)
    except ValueError:
        raise ValueError(f"Unknown style rule '{rule}'. Supported: {[r.value for r in StyleRule]}")

    name = name.strip()
    if not name:
        raise ValueError("Style name cannot be empty.")

    existing = await _find_style(db, venue_id, name)
    if existing:
        existing.rule = rule_enum
        await db.commit()
        await db.refresh(existing)
        return existing

    style = VenueStyle(venue_id=venue_id, name=name, rule=rule_enum)
    db.add(style)
    await db.commit()
    await db.refresh(style)
    return style


async def update_style_rule(db: AsyncSession, venue_id: int, style_id: int, rule: str) -> Optional[VenueStyle]:
    try:
        rule_enum = StyleRule(rule)
    except ValueError:
        raise ValueError(f"Unknown style rule '{rule}'. Supported: {[r.value for r in StyleRule]}")

    result = await db.execute(
        select(VenueStyle).where(VenueStyle.id == style_id, VenueStyle.venue_id == venue_id)
    )
    style = result.scalars().first()
    if not style:
        return None
    style.rule = rule_enum
    await db.commit()
    await db.refresh(style)
    return style


async def delete_style(db: AsyncSession, venue_id: int, style_id: int) -> bool:
    result = await db.execute(
        select(VenueStyle).where(VenueStyle.id == style_id, VenueStyle.venue_id == venue_id)
    )
    style = result.scalars().first()
    if not style:
        return False
    await db.delete(style)
    await db.commit()
    return True


async def check_style_for_add(db: AsyncSession, venue: Venue, style_name: Optional[str]) -> str:
    """Returns 'allowed', 'needs_unlock', or 'prohibited'. Free venues (or a
    request with no style, or a style that doesn't match any configured
    rule) are always 'allowed'."""
    if venue.subscription_tier != "pro" or not style_name:
        return "allowed"

    style = await _find_style(db, venue.id, style_name)
    if not style:
        return "allowed"

    if style.rule == StyleRule.PROHIBITED:
        return "prohibited"
    if style.rule == StyleRule.PREMIUM_ONLY:
        return "needs_unlock"
    return "allowed"
