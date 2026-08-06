import io
from typing import List, Dict, Any, Optional

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.database import get_db
from backend.app.models import Venue
from backend.app.config import settings
from backend.app.schemas import (
    TrackSearchResult, QueueAddRequest, QueueAddPremiumRequest, PriorityTierResponse,
    SimulatePaymentRequest, VenueStyleResponse,
)
from backend.app.media_providers.factory import MediaProviderFactory
from backend.app.services.queue_service import get_current_queue_response, add_track_to_queue
from backend.app.services.payment_service import get_priority_tiers, process_mock_payment, unlock_premium_style_and_add
from backend.app.services import style_service, autoplay_service

# Public, slug-scoped endpoints -- what a guest's phone talks to after
# scanning the venue's QR code / opening /v/{slug}. No auth: the slug itself
# is the only thing identifying which venue's queue a request touches.
router = APIRouter(prefix="/api/v/{slug}", tags=["Guest (Venue-Scoped)"])


async def _get_venue_or_404(db: AsyncSession, slug: str) -> Venue:
    result = await db.execute(select(Venue).where(Venue.slug == slug))
    venue = result.scalars().first()
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found.")
    return venue


@router.get("/meta")
async def get_venue_meta(slug: str, db: AsyncSession = Depends(get_db)):
    """Lets the guest page confirm the slug is real and show the venue name."""
    venue = await _get_venue_or_404(db, slug)
    return {"name": venue.name, "slug": venue.slug}


@router.get("/search", response_model=List[TrackSearchResult])
async def search_tracks(
    slug: str,
    q: str = Query(..., min_length=1),
    provider: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Search music tracks via this venue's active media provider strategy."""
    venue = await _get_venue_or_404(db, slug)
    try:
        # Previously defaulted to a single global settings.ACTIVE_PROVIDER --
        # now defaults to this venue's own setting when the caller doesn't
        # explicitly override it.
        active_provider = MediaProviderFactory.get_provider(provider or venue.active_provider)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    try:
        return await active_provider.search_tracks(q)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue", response_model=List[Dict[str, Any]])
async def get_queue(slug: str, db: AsyncSession = Depends(get_db)):
    """Fetch this venue's current playing & queued tracks ordered by priority."""
    venue = await _get_venue_or_404(db, slug)
    return await get_current_queue_response(db, venue.id)


@router.get("/styles", response_model=List[VenueStyleResponse])
async def list_styles(slug: str, db: AsyncSession = Depends(get_db)):
    """Public style list for the add-song flow. Empty for Free venues, or
    Pro venues that haven't configured any styles yet."""
    venue = await _get_venue_or_404(db, slug)
    if venue.subscription_tier != "pro":
        return []
    return await style_service.list_venue_styles(db, venue.id)


@router.post("/queue/add")
async def add_to_queue(slug: str, req: QueueAddRequest, db: AsyncSession = Depends(get_db)):
    """Add a new track to this venue's queue. A style tagged 'prohibited'
    is rejected outright; one tagged 'premium_only' is rejected here too,
    with a 402 pointing the client at POST /queue/add-premium instead."""
    venue = await _get_venue_or_404(db, slug)

    decision = await style_service.check_style_for_add(db, venue, req.style)
    if decision == "prohibited":
        raise HTTPException(status_code=403, detail=f"'{req.style}' isn't accepted at this venue.")
    if decision == "needs_unlock":
        raise HTTPException(
            status_code=402,
            detail={
                "requires_unlock": True,
                "style": req.style,
                "unlock_fee": venue.premium_style_unlock_fee,
                "message": f"'{req.style}' is a premium-only style here -- pay ${venue.premium_style_unlock_fee:.2f} to add it.",
            },
        )

    try:
        result = await add_track_to_queue(db, venue.id, req)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    await autoplay_service.maybe_fill_queue(db, venue.id)
    return result


@router.post("/queue/add-premium")
async def add_premium_to_queue(slug: str, req: QueueAddPremiumRequest, db: AsyncSession = Depends(get_db)):
    """Pay this venue's flat premium-style-unlock fee to add a song tagged
    with a 'premium_only' style."""
    venue = await _get_venue_or_404(db, slug)
    try:
        result = await unlock_premium_style_and_add(db, venue.id, req)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Payment processing failed: {str(e)}")
    await autoplay_service.maybe_fill_queue(db, venue.id)
    return result


@router.get("/priority-tiers", response_model=List[PriorityTierResponse])
async def list_priority_tiers(slug: str, db: AsyncSession = Depends(get_db)):
    """List this venue's mock payment priority tiers."""
    venue = await _get_venue_or_404(db, slug)
    return await get_priority_tiers(db, venue.id)


@router.post("/payments/simulate")
async def simulate_payment(slug: str, req: SimulatePaymentRequest, db: AsyncSession = Depends(get_db)):
    """Process a simulated priority payment to bump a song in this venue's queue."""
    venue = await _get_venue_or_404(db, slug)
    try:
        return await process_mock_payment(db, venue.id, req)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Payment processing failed: {str(e)}")


@router.get("/qr.svg")
async def guest_qr_code(slug: str, db: AsyncSession = Depends(get_db)):
    """Public QR code encoding this venue's guest request URL -- meant to be
    printed/displayed at the venue, no auth needed (the slug isn't sensitive)."""
    venue = await _get_venue_or_404(db, slug)
    target_url = f"{settings.PUBLIC_ORIGIN}/v/{venue.slug}" if settings.PUBLIC_ORIGIN else f"/v/{venue.slug}"
    img = qrcode.make(target_url, image_factory=qrcode.image.svg.SvgImage)
    buf = io.BytesIO()
    img.save(buf)
    return Response(content=buf.getvalue(), media_type="image/svg+xml")
