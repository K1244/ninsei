from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.database import get_db
from backend.app.models import Venue
from backend.app.schemas import VenueRegisterRequest, VenueLoginRequest, VenueResponse
from backend.app.auth import (
    hash_password, verify_password, set_session_cookie, clear_session_cookie,
    get_current_venue, generate_unique_slug,
)
from backend.app.services.payment_service import seed_priority_tiers_for_venue

router = APIRouter(prefix="/api/auth", tags=["Venue Auth"])


@router.post("/register", response_model=VenueResponse)
async def register(req: VenueRegisterRequest, response: Response, db: AsyncSession = Depends(get_db)):
    email = req.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    if not req.venue_name.strip():
        raise HTTPException(status_code=400, detail="Venue name is required.")

    existing = await db.execute(select(Venue).where(Venue.email == email))
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail="An account with that email already exists.")

    slug = await generate_unique_slug(db, req.venue_name)
    venue = Venue(
        slug=slug,
        name=req.venue_name.strip(),
        email=email,
        password_hash=hash_password(req.password),
    )
    db.add(venue)
    await db.commit()
    await db.refresh(venue)
    await seed_priority_tiers_for_venue(db, venue.id)

    set_session_cookie(response, venue.id)
    return venue


@router.post("/login", response_model=VenueResponse)
async def login(req: VenueLoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    email = req.email.strip().lower()
    result = await db.execute(select(Venue).where(Venue.email == email))
    venue = result.scalars().first()

    # Same "invalid email or password" message whether the account doesn't exist
    # or the password is wrong, so login can't be used to enumerate registered emails.
    if not venue or not verify_password(req.password, venue.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    set_session_cookie(response, venue.id)
    return venue


@router.post("/logout")
async def logout(response: Response):
    clear_session_cookie(response)
    return {"success": True}


@router.get("/me", response_model=VenueResponse)
async def me(venue: Venue = Depends(get_current_venue)):
    return venue
