from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import AVATAR_OPTIONS
from backend.app.database import get_db
from backend.app.models import User
from backend.app.schemas import UserIdentifyRequest, UserResponse, UserProfileUpdate
from backend.app.services.user_service import identify_or_create, update_profile, get_optional_user

router = APIRouter(prefix="/api/users", tags=["Patrons"])


@router.get("/avatar-options")
async def avatar_options():
    """Public (no identity needed) -- the picker a patron chooses
    User.avatar from. See config.AVATAR_OPTIONS for how these are cut from
    the raw reference sheets."""
    return AVATAR_OPTIONS


@router.post("/identify", response_model=UserResponse)
async def identify(req: UserIdentifyRequest, db: AsyncSession = Depends(get_db)):
    """
    Called on first landing-room visit (and on every later one, sending back
    whatever token localStorage has). Always succeeds -- an unknown/missing
    token just mints a fresh anonymous identity, same as device pairing's
    register-or-refresh flow.
    """
    user = await identify_or_create(db, req.token)
    return user


@router.patch("/me", response_model=UserResponse)
async def update_me(
    req: UserProfileUpdate,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    if user is None:
        raise HTTPException(status_code=401, detail="Unknown patron -- call /api/users/identify first.")
    try:
        return await update_profile(db, user, req.display_name, req.avatar)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))


@router.get("/me", response_model=UserResponse)
async def get_me(user: User | None = Depends(get_optional_user)):
    if user is None:
        raise HTTPException(status_code=401, detail="Unknown patron -- call /api/users/identify first.")
    return user
