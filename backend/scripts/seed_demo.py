"""
Demo/test data for local and staging use -- PLAN.md section 12's five venues,
covering every VenueMode + module combination the MVP acceptance criteria
(PLAN.md section 16) need to click through: a fully open pub, a members-only
bar with tiered plans, a private birthday party with observers + request
access, an invite-only wedding, and a public club night with merch.

Idempotent and safe to re-run: each venue uses a fixed (non-random) slug --
unlike auth_router.generate_unique_slug's normal random-suffixed slugs -- and
a venue whose slug already exists is left untouched rather than duplicated.

Usage:
    python -m backend.scripts.seed_demo
"""
import asyncio

from sqlalchemy import select

from backend.app.database import init_db, AsyncSessionLocal
from backend.app.auth import hash_password, slugify
from backend.app.models import Venue, VenueMode, Event, MembershipPlan, Product
from backend.app.services.payment_service import seed_priority_tiers_for_venue

DEMO_PASSWORD = "clubowna-demo"


async def _get_or_create_venue(db, *, name, email, mode, modules, description, address, scene_theme) -> tuple[Venue, bool]:
    slug = slugify(name)
    existing = (await db.execute(select(Venue).where(Venue.slug == slug))).scalars().first()
    if existing:
        return existing, False

    venue = Venue(
        slug=slug,
        name=name,
        email=email,
        password_hash=hash_password(DEMO_PASSWORD),
        mode=mode,
        description=description,
        address=address,
        scene_theme=scene_theme,
    )
    venue.available_modules = modules
    db.add(venue)
    await db.commit()
    await db.refresh(venue)
    if "jukebox" in modules:
        await seed_priority_tiers_for_venue(db, venue.id)
    return venue, True


async def seed() -> None:
    await init_db()
    async with AsyncSessionLocal() as db:
        created = []

        # 1. Pixel Pub -- fully open, jukebox only.
        pub, is_new = await _get_or_create_venue(
            db, name="Pixel Pub", email="demo+pixelpub@clubowna.com",
            mode=VenueMode.PUBLIC, modules=["jukebox"],
            description="A no-fuss neighborhood pub. Walk in, queue a song, have a beer.",
            address="1 Retro Street", scene_theme="pub",
        )
        if is_new:
            created.append(pub.name)

        # 2. Neon Den -- members-only bar, QR-checked, tiered plans.
        neon, is_new = await _get_or_create_venue(
            db, name="Neon Den", email="demo+neonden@clubowna.com",
            mode=VenueMode.MEMBERS_ONLY, modules=["jukebox", "qr_entry", "memberships"],
            description="Members-only cocktail bar. Show your pass at the door.",
            address="14 Arcade Alley", scene_theme="bar",
        )
        if is_new:
            created.append(neon.name)
            for plan_kwargs in [
                dict(name="Regular", price=9.0, interval="monthly",
                     perks="Members-only entry, house jukebox access"),
                dict(name="VIP", price=25.0, interval="monthly",
                     perks="Skip the line, priority queue, reserved booth"),
            ]:
                db.add(MembershipPlan(
                    venue_id=neon.id, access_level=VenueMode.MEMBERS_ONLY,
                    qr_access_enabled=True, **plan_kwargs,
                ))
            await db.commit()

        # 3. Birthday Basement -- private birthday party, observers + requests on.
        basement, is_new = await _get_or_create_venue(
            db, name="Birthday Basement", email="demo+basement@clubowna.com",
            mode=VenueMode.PUBLIC, modules=["jukebox", "observers", "request_access", "qr_entry"],
            description="A basement venue currently hosting a private birthday party.",
            address="8 Cellar Court", scene_theme="lounge",
        )
        if is_new:
            created.append(basement.name)
            event = Event(
                venue_id=basement.id, title="Sam's 30th Birthday", type="birthday",
                organizer_name="Sam", access_mode=VenueMode.PRIVATE_EVENT,
                observer_mode=True, request_access_allowed=True,
                guest_capacity=40, public_visibility=True,
            )
            event.scene_props = ["cake", "balloons"]
            db.add(event)
            await db.commit()

        # 4. Wedding Hall -- invite-only wedding, observers can watch, no requests.
        wedding, is_new = await _get_or_create_venue(
            db, name="Wedding Hall", email="demo+weddinghall@clubowna.com",
            mode=VenueMode.PUBLIC, modules=["jukebox", "observers", "qr_entry", "donations"],
            description="An elegant hall currently hosting a wedding celebration.",
            address="3 Chapel Row", scene_theme="lounge",
        )
        if is_new:
            created.append(wedding.name)
            event = Event(
                venue_id=wedding.id, title="Alex & Jordan's Wedding", type="wedding",
                organizer_name="Alex & Jordan", access_mode=VenueMode.INVITE_ONLY,
                observer_mode=True, request_access_allowed=False,
                guest_capacity=120, public_visibility=True,
            )
            event.scene_props = ["wedding_decor", "flowers"]
            db.add(event)
            # Donations/gifting is a future module (PLAN.md section 14) --
            # a placeholder product stands in for it for MVP.
            db.add(Product(
                venue_id=wedding.id, name="Wedding Gift", description="Send the couple a gift (placeholder for a future gifting module).",
                price=20.0, billing_type="one_time", visibility=True,
            ))
            await db.commit()

        # 5. Night Cartridge -- public club night, DJ booth, merch.
        cartridge, is_new = await _get_or_create_venue(
            db, name="Night Cartridge", email="demo+nightcartridge@clubowna.com",
            mode=VenueMode.PUBLIC, modules=["jukebox", "products", "qr_entry"],
            description="A public club night with a DJ booth and a bigger crowd.",
            address="99 Cartridge Boulevard", scene_theme="club",
        )
        if is_new:
            created.append(cartridge.name)
            event = Event(
                venue_id=cartridge.id, title="Night Cartridge: Club Night", type="club_night",
                access_mode=VenueMode.PUBLIC, observer_mode=False,
                request_access_allowed=False, guest_capacity=200, public_visibility=True,
            )
            db.add(event)
            db.add(Product(
                venue_id=cartridge.id, name="Night Cartridge T-Shirt",
                description="Pixel-art logo tee.", price=15.0,
                billing_type="one_time", visibility=True,
            ))
            await db.commit()

        if created:
            print(f"Seeded {len(created)} demo venue(s): {', '.join(created)}")
        else:
            print("All 5 demo venues already exist -- nothing to do.")
        print(f"(Demo login password for all seeded venues: {DEMO_PASSWORD!r})")


if __name__ == "__main__":
    asyncio.run(seed())
