"""
Products/services a venue sells outside of a recurring membership (merch,
donations, one-time entry, ...) -- venue-admin CRUD plus the guest-facing
purchase flow. Same mock-payment/revenue-split pattern as payment_service.py.
"""
import uuid
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.models import Product, Purchase, TransactionStatus, Venue, User
from backend.app.schemas import ProductCreate, ProductUpdate
from backend.app.services.payment_service import _split_amount


async def list_products(db: AsyncSession, venue_id: int, visible_only: bool = False) -> List[Product]:
    stmt = select(Product).where(Product.venue_id == venue_id).order_by(Product.price.asc())
    if visible_only:
        stmt = stmt.where(Product.enabled.is_(True), Product.visibility.is_(True))
    return list((await db.execute(stmt)).scalars().all())


async def get_product(db: AsyncSession, venue_id: int, product_id: int) -> Optional[Product]:
    result = await db.execute(select(Product).where(Product.id == product_id, Product.venue_id == venue_id))
    return result.scalars().first()


async def create_product(db: AsyncSession, venue_id: int, req: ProductCreate) -> Product:
    product = Product(
        venue_id=venue_id,
        name=req.name.strip(),
        description=req.description,
        price=req.price,
        billing_type=req.billing_type,
        visibility=req.visibility,
    )
    if req.grants_entitlements:
        product.grants_entitlements = req.grants_entitlements
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


async def update_product(db: AsyncSession, venue_id: int, product_id: int, req: ProductUpdate) -> Optional[Product]:
    product = await get_product(db, venue_id, product_id)
    if not product:
        return None
    if req.name is not None:
        product.name = req.name.strip()
    if req.description is not None:
        product.description = req.description
    if req.price is not None:
        product.price = req.price
    if req.billing_type is not None:
        product.billing_type = req.billing_type
    if req.enabled is not None:
        product.enabled = req.enabled
    if req.visibility is not None:
        product.visibility = req.visibility
    if req.grants_entitlements is not None:
        product.grants_entitlements = req.grants_entitlements
    await db.commit()
    await db.refresh(product)
    return product


async def delete_product(db: AsyncSession, venue_id: int, product_id: int) -> bool:
    product = await get_product(db, venue_id, product_id)
    if not product:
        return False
    await db.delete(product)
    await db.commit()
    return True


async def purchase_product(db: AsyncSession, venue: Venue, user: User, product_id: int, payment_method: str) -> dict:
    product = await get_product(db, venue.id, product_id)
    if not product or not product.enabled:
        raise ValueError("Product not found.")

    venue_amount, app_amount = _split_amount(venue, product.price)
    txn_ref = f"TXN_{uuid.uuid4().hex[:8].upper()}"

    # "included_in_membership" one_time_entry products still grant the
    # venue_entry-flavored purchase used by access_service._has_event_entitlement
    # when their kind matches -- for MVP every purchasable product just uses
    # its own name as the Purchase kind bucket ('product'); entry-granting
    # ones are the ones the owner also tagged with the "venue_entry"
    # entitlement code (see grants_entitlements) and access_service checks
    # kind == 'one_time_entry' specifically, so mirror that when relevant.
    kind = "one_time_entry" if "venue_entry" in product.grants_entitlements else "product"

    purchase = Purchase(
        user_id=user.id,
        venue_id=venue.id,
        kind=kind,
        product_id=product.id,
        amount=product.price,
        status=TransactionStatus.COMPLETED,
        payment_method=payment_method,
        transaction_reference=txn_ref,
        venue_amount=venue_amount,
        app_amount=app_amount,
    )
    db.add(purchase)
    await db.commit()
    await db.refresh(purchase)

    return {
        "success": True,
        "transaction_reference": txn_ref,
        "product_name": product.name,
        "amount": product.price,
        "message": f"Purchased '{product.name}' -- ${product.price:.2f} charged (mock payment).",
    }
