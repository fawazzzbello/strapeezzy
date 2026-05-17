# app/routes/orders.py
import json
import os
import random
import string
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from app.models.database import get_db, Order, ActivityLog, AdminUser, Role
from app.models.schemas import (
    OrderCreate, FulfillmentUpdate, OrderStatusUpdate, OrderOut, OrderStats
)
from app.middleware.auth import get_current_user, require_roles, require_superadmin
from app.services.notifications import (
    send_email, send_sms,
    template_order_confirm, template_shipping_confirm
)

router = APIRouter(prefix="/api/orders", tags=["orders"])


def generate_order_number() -> str:
    ts = str(int(datetime.now().timestamp()))[-6:]
    rnd = ''.join(random.choices(string.digits, k=3))
    return f"SZ-{ts}-{rnd}"


def log_action(db, user, action, entity=None, entity_id=None, details=None):
    db.add(ActivityLog(
        admin_id=user.id,
        admin_username=user.username,
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id else None,
        details=json.dumps(details or {}),
    ))
    db.commit()


def order_to_dict(o: Order) -> dict:
    return {
        "id": o.id, "order_number": o.order_number,
        "stripe_payment_intent": o.stripe_payment_intent,
        "customer_name": o.customer_name, "customer_email": o.customer_email,
        "customer_phone": o.customer_phone, "shipping_address": o.shipping_address,
        "product_name": o.product_name, "product_variant": o.product_variant,
        "quantity": o.quantity, "unit_price": o.unit_price, "total_amount": o.total_amount,
        "currency": o.currency, "status": o.status,
        "fulfillment_status": o.fulfillment_status, "tracking_number": o.tracking_number,
        "tracking_carrier": o.tracking_carrier, "tracking_url": o.tracking_url,
        "notes": o.notes,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
        "shipped_at": o.shipped_at.isoformat() if o.shipped_at else None,
        "delivered_at": o.delivered_at.isoformat() if o.delivered_at else None,
    }


# ── STATS ──
@router.get("/stats", response_model=OrderStats)
async def get_stats(
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.VIEWER, Role.ADMIN, Role.SUPERADMIN)),
):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)

    total_revenue = db.query(func.coalesce(func.sum(Order.total_amount), 0)).filter(
        Order.status == "paid"
    ).scalar()

    by_product = (
        db.query(Order.product_name, func.count(Order.id).label("count"))
        .group_by(Order.product_name)
        .order_by(func.count(Order.id).desc())
        .all()
    )

    return OrderStats(
        total_orders=db.query(Order).count(),
        total_revenue=total_revenue,
        unfulfilled=db.query(Order).filter(
            Order.fulfillment_status == "unfulfilled", Order.status == "paid"
        ).count(),
        shipped=db.query(Order).filter(Order.fulfillment_status == "shipped").count(),
        delivered=db.query(Order).filter(Order.fulfillment_status == "delivered").count(),
        today=db.query(Order).filter(Order.created_at >= today_start).count(),
        this_week=db.query(Order).filter(Order.created_at >= week_start).count(),
        by_product=[{"product_name": r.product_name, "count": r.count} for r in by_product],
    )


# ── LIST ──
@router.get("/")
async def list_orders(
    page: int = 1,
    limit: int = 50,
    status: str = "",
    fulfillment_status: str = "",
    search: str = "",
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.VIEWER, Role.ADMIN, Role.SUPERADMIN)),
):
    q = db.query(Order)
    if status:
        q = q.filter(Order.status == status)
    if fulfillment_status:
        q = q.filter(Order.fulfillment_status == fulfillment_status)
    if search:
        like = f"%{search}%"
        q = q.filter(
            Order.customer_email.ilike(like) |
            Order.customer_name.ilike(like) |
            Order.order_number.ilike(like)
        )
    total = q.count()
    orders = q.order_by(Order.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"orders": [order_to_dict(o) for o in orders], "total": total, "page": page, "limit": limit}


# ── GET ONE ──
@router.get("/{order_id}")
async def get_order(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.VIEWER, Role.ADMIN, Role.SUPERADMIN)),
):
    # Try by ID or order_number
    try:
        o = db.query(Order).filter(Order.id == int(order_id)).first()
    except ValueError:
        o = db.query(Order).filter(Order.order_number == order_id).first()
    if not o:
        raise HTTPException(404, "Order not found")
    return order_to_dict(o)


# ── FULFILL ──
@router.patch("/{order_id}/fulfill")
async def fulfill_order(
    order_id: int,
    body: FulfillmentUpdate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    o = db.query(Order).filter(Order.id == order_id).first()
    if not o:
        raise HTTPException(404, "Order not found")

    prev_status = o.fulfillment_status
    just_shipped = body.fulfillment_status == "shipped" and prev_status != "shipped"
    just_delivered = body.fulfillment_status == "delivered" and prev_status != "delivered"

    if body.fulfillment_status:
        o.fulfillment_status = body.fulfillment_status
    if body.tracking_number is not None:
        o.tracking_number = body.tracking_number
    if body.tracking_carrier is not None:
        o.tracking_carrier = body.tracking_carrier
    if body.tracking_url is not None:
        o.tracking_url = body.tracking_url
    if body.notes is not None:
        o.notes = body.notes
    if just_shipped:
        o.shipped_at = datetime.now(timezone.utc)
    if just_delivered:
        o.delivered_at = datetime.now(timezone.utc)
    o.updated_at = datetime.now(timezone.utc)
    db.commit()

    log_action(db, current_user, "FULFILL_ORDER", "orders", order_id,
               {"status": body.fulfillment_status, "tracking": body.tracking_number})

    if just_shipped:
        od = order_to_dict(o)
        async def _notify():
            subject, html = template_shipping_confirm(od)
            await send_email(od["customer_email"], od["customer_name"], subject, html)
            if od.get("customer_phone"):
                msg = (f"📦 Your Strapeezzy order {od['order_number']} has shipped!"
                       f" Track: {od.get('tracking_url') or od.get('tracking_number') or 'check email'}")
                await send_sms(od["customer_phone"], msg)
        background.add_task(_notify)

    return {"success": True, "order": order_to_dict(o)}


# ── UPDATE STATUS ──
@router.patch("/{order_id}/status")
async def update_status(
    order_id: int,
    body: OrderStatusUpdate,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    o = db.query(Order).filter(Order.id == order_id).first()
    if not o:
        raise HTTPException(404, "Order not found")
    o.status = body.status
    if body.notes:
        o.notes = body.notes
    o.updated_at = datetime.now(timezone.utc)
    db.commit()
    log_action(db, current_user, "UPDATE_ORDER_STATUS", "orders", order_id, {"status": body.status})
    return {"success": True}


# ── MANUAL CREATE ──
@router.post("/manual", status_code=201)
async def create_manual_order(
    body: OrderCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    order_number = generate_order_number()
    total = body.unit_price * body.quantity
    o = Order(
        order_number=order_number,
        customer_name=body.customer_name,
        customer_email=body.customer_email,
        customer_phone=body.customer_phone or "",
        product_name=body.product_name,
        product_variant=body.product_variant or "",
        quantity=body.quantity,
        unit_price=body.unit_price,
        total_amount=total,
        shipping_address=body.shipping_address or "",
        notes=body.notes or "",
        status="manual",
        fulfillment_status="unfulfilled",
    )
    db.add(o)
    db.commit()
    db.refresh(o)

    od = order_to_dict(o)
    async def _notify():
        subject, html = template_order_confirm(od)
        await send_email(od["customer_email"], od["customer_name"], subject, html)
    background.add_task(_notify)

    log_action(db, current_user, "CREATE_MANUAL_ORDER", "orders", o.id, {"order_number": order_number})
    return {"success": True, "order": od}


# ── STRIPE SYNC ──
@router.post("/stripe-sync")
async def stripe_sync(
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    """Pull all succeeded PaymentIntents from Stripe and create any missing orders."""
    import stripe as stripe_lib
    stripe_lib.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    if not stripe_lib.api_key or stripe_lib.api_key.startswith("sk_test_YOUR"):
        raise HTTPException(503, "Stripe not configured")

    synced = 0
    skipped = 0
    errors = 0
    starting_after = None

    while True:
        params = {"limit": 100}
        if starting_after:
            params["starting_after"] = starting_after
        try:
            page = stripe_lib.PaymentIntent.list(**params)
        except stripe_lib.StripeError as e:
            raise HTTPException(502, f"Stripe error: {e}")

        for pi in page.data:
            if pi.status != "succeeded":
                skipped += 1
                continue
            if db.query(Order).filter(Order.stripe_payment_intent == pi.id).first():
                skipped += 1
                continue
            try:
                meta = pi.get("metadata") or {}
                ts = str(int(datetime.now(timezone.utc).timestamp()))[-6:]
                rnd = ''.join(random.choices(string.digits, k=3))
                o = Order(
                    order_number=f"SZ-{ts}-{rnd}",
                    stripe_payment_intent=pi.id,
                    customer_name=meta.get("customer_name") or "Customer",
                    customer_email=meta.get("customer_email") or "",
                    customer_phone=meta.get("customer_phone") or "",
                    shipping_address=meta.get("shipping_address") or "",
                    product_name=meta.get("product_name") or "Pioneer Strap",
                    product_variant=meta.get("product_colorway") or meta.get("product_variant") or "",
                    quantity=1,
                    unit_price=pi["amount"],
                    total_amount=pi["amount"],
                    currency=pi.get("currency", "gbp"),
                    status="paid",
                    fulfillment_status="unfulfilled",
                )
                db.add(o)
                db.commit()
                synced += 1
            except Exception:
                errors += 1
                db.rollback()

        if not page.has_more:
            break
        starting_after = page.data[-1].id

    log_action(db, current_user, "STRIPE_SYNC", "orders", "all",
               {"synced": synced, "skipped": skipped, "errors": errors})
    return {"success": True, "synced": synced, "skipped": skipped, "errors": errors}


# ── DELETE (superadmin only) ──
@router.delete("/{order_id}", status_code=204)
async def delete_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_superadmin()),
):
    o = db.query(Order).filter(Order.id == order_id).first()
    if not o:
        raise HTTPException(404, "Order not found")
    log_action(db, current_user, "DELETE_ORDER", "orders", order_id, {"order_number": o.order_number})
    db.delete(o)
    db.commit()
