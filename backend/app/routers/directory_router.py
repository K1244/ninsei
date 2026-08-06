"""
Public venue directory -- the one genuinely new browsing surface (PLAN.md
section 6): previously a guest could only ever land on a venue via its known
slug/QR code; this is what feeds the venue-hub map screen.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.database import get_db
from backend.app.models import Venue, VenueMode, User
from backend.app.schemas import (
    VenueDirectoryItem, VenuePublicProfile, EventResponse,
    MembershipPlanResponse, ProductResponse, AccessSummaryResponse,
)
from backend.app.services import access_service, membership_service, product_service
from backend.app.services.user_service import get_optional_user

router = APIRouter(prefix="/api/venues", tags=["Venue Directory"])


def _event_response(event) -> Optional[EventResponse]:
    # str-subclassed enums (VenueMode) and the scene_props/is_active
    # properties both validate straight off the ORM object -- see
    # model_config's from_attributes on EventResponse.
    return EventResponse.model_validate(event) if event else None


@router.get("", response_model=List[VenueDirectoryItem])
async def list_venues(db: AsyncSession = Depends(get_db)):
    """Every non-closed venue, for the hub map. Closed venues are omitted
    entirely rather than shown greyed-out -- simplest MVP behavior; revisit
    if owners want a "closed today, check back later" state instead."""
    result = await db.execute(select(Venue).where(Venue.mode != VenueMode.CLOSED).order_by(Venue.name.asc()))
    venues = result.scalars().all()
    items = []
    for venue in venues:
        active_event = await access_service.get_active_event(db, venue.id)
        items.append(VenueDirectoryItem(
            slug=venue.slug,
            name=venue.name,
            description=venue.description,
            address=venue.address,
            scene_theme=venue.scene_theme,
            mode=venue.mode.value,
            active_event=_event_response(active_event),
            available_modules=venue.available_modules,
        ))
    return items


@router.get("/{slug}", response_model=VenuePublicProfile)
async def venue_public_profile(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
):
    result = await db.execute(select(Venue).where(Venue.slug == slug))
    venue = result.scalars().first()
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found.")

    ctx = await access_service.evaluate_access(db, venue, user)
    plans = await membership_service.list_plans(db, venue.id, enabled_only=True) if "memberships" in venue.available_modules else []
    products = await product_service.list_products(db, venue.id, visible_only=True) if "products" in venue.available_modules else []

    return VenuePublicProfile(
        slug=venue.slug,
        name=venue.name,
        description=venue.description,
        address=venue.address,
        scene_theme=venue.scene_theme,
        mode=venue.mode.value,
        active_event=_event_response(ctx.active_event),
        available_modules=venue.available_modules,
        membership_plans=[MembershipPlanResponse.model_validate(p) for p in plans],
        products=[ProductResponse.model_validate(p) for p in products],
        access=AccessSummaryResponse(
            can_view_venue=ctx.can_view_venue,
            can_enter_venue=ctx.can_enter_venue,
            can_observe_event=ctx.can_observe_event and "observers" in venue.available_modules,
            can_request_access=ctx.can_request_access and "request_access" in venue.available_modules,
            can_use_jukebox=ctx.can_use_jukebox and "jukebox" in venue.available_modules,
            can_show_qr=ctx.can_show_qr and "qr_entry" in venue.available_modules,
            can_buy_product=ctx.can_buy_product and "products" in venue.available_modules,
            can_join_membership=ctx.can_join_membership and "memberships" in venue.available_modules,
            reason=ctx.reason,
            active_event=_event_response(ctx.active_event),
        ),
    )
