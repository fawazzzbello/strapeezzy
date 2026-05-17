# app/routes/orders.py
import json
import os
import random
import string
import asyncio
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from app.models.database import get_db, Order, ActivityLog, AdminUser, Role
from app.models.schemas import (
    OrderSubmit, OrderCreate, FulfillmentUpdate, OrderStatusUpdate, OrderOut, OrderStats
)
from app.middleware.auth import get_current_user, require_roles, require_superadmin
from app.services.notifications import (
    send_email, send_sms,
    template_order_confirm, template_shipping_confirm
)

router = APIRouter(prefix="/api/orders", tags=["orders"])


# ── PUBLIC: SUBMIT ORDER ──
@router.post("/submit", status_code=201, include_in_schema=True)
async def submit_order(
    body: OrderSubmit,
    db: Session = Depends(get_db),
):
    """Public endpoint for buyers to submit an order for approval."""
    order_number = generate_order_number()
    o = Order(
        order_number=order_number,
        customer_name=body.customer_name,
        customer_email=body.customer_email,
        customer_phone=body.customer_phone,
        product_name=body.product_name,
        product_brand=body.product_brand,
        product_link=body.product_link,
        quantity=1,
        unit_price=0,
        total_amount=0,
        status="pending_approval",
        fulfillment_status="unfulfilled",
    )
    db.add(o)
    db.commit()
    db.refresh(o)

    return {"success": True, "order_number": order_number, "message": "Order submitted for approval"}


# ── PUBLIC: TRACK ORDER ──
@router.get("/track/{order_number}", include_in_schema=True)
async def track_order(
    order_number: str,
    email: str = "",
    db: Session = Depends(get_db),
):
    """Public endpoint to track order by order_number and email for verification."""
    o = db.query(Order).filter(Order.order_number == order_number).first()
    if not o:
        raise HTTPException(404, "Order not found")

    # Simple verification: email must match or be empty (open tracking)
    if email and o.customer_email.lower() != email.lower():
        raise HTTPException(403, "Email does not match this order")

    status_labels = {
        "pending_approval": "🔄 Pending Review",
        "approved": "✅ Approved",
        "payment_pending": "💳 Awaiting Payment",
        "paid": "💰 Payment Received",
        "cancelled": "❌ Cancelled",
    }

    fulfillment_labels = {
        "unfulfilled": "📦 Not Yet Packed",
        "in_progress": "📦 Being Packed",
        "shipped": "🚚 On the Way",
        "delivered": "✨ Delivered",
    }

    return {
        "order_number": o.order_number,
        "status": o.status,
        "status_label": status_labels.get(o.status, o.status),
        "fulfillment_status": o.fulfillment_status,
        "fulfillment_label": fulfillment_labels.get(o.fulfillment_status, o.fulfillment_status),
        "customer_name": o.customer_name,
        "product_name": o.product_name,
        "product_brand": o.product_brand,
        "total_amount": o.total_amount,
        "currency": o.currency,
        "tracking_number": o.tracking_number,
        "tracking_carrier": o.tracking_carrier,
        "tracking_url": o.tracking_url,
        "shipping_address": o.shipping_address,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "shipped_at": o.shipped_at.isoformat() if o.shipped_at else None,
        "delivered_at": o.delivered_at.isoformat() if o.delivered_at else None,
    }


# ── ADMIN: APPROVE ORDER ──
@router.patch("/{order_id}/approve", status_code=200)
async def approve_order(
    order_id: int,
    unit_price: int,
    notes: str = "",
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    """Admin approves an order and sets the price. Generates Stripe payment link."""
    import stripe as stripe_lib

    o = db.query(Order).filter(Order.id == order_id).first()
    if not o:
        raise HTTPException(404, "Order not found")
    if o.status != "pending_approval":
        raise HTTPException(400, "Order can only be approved if it's pending approval")

    o.status = "approved"
    o.unit_price = unit_price
    o.total_amount = unit_price
    o.quantity = 1
    if notes:
        o.notes = notes
    o.updated_at = datetime.now(timezone.utc)

    # Generate Stripe payment link
    stripe_link_url = None
    stripe_secret = os.getenv("STRIPE_SECRET_KEY", "")
    if stripe_secret and not stripe_secret.startswith("sk_test_YOUR"):
        try:
            stripe_lib.api_key = stripe_secret
            payment_link = stripe_lib.PaymentLink.create(
                line_items=[{
                    "price_data": {
                        "currency": "gbp",
                        "unit_amount": unit_price,
                        "product_data": {
                            "name": o.product_name,
                            "description": f"{o.product_brand or ''} - {o.product_link or ''}"[:250],
                        },
                    },
                    "quantity": 1,
                }],
                custom_text={
                    "terms_of_service_acceptance_text": "I agree to the payment terms",
                },
                after_completion={
                    "type": "redirect",
                    "redirect": {"url": f"{os.getenv('FRONTEND_URL', 'https://lidle.example.com')}/order-tracking?order={o.order_number}"},
                },
                metadata={
                    "order_number": o.order_number,
                    "customer_email": o.customer_email,
                },
            )
            stripe_link_url = payment_link.url
        except stripe_lib.StripeError as e:
            print(f"⚠️ Stripe payment link generation failed: {e}")

    db.commit()

    # Send approval email with payment link
    from app.services.notifications import send_email
    if o.customer_email:
        async def _notify():
            subject = f"Order {o.order_number} Approved - Ready to Pay"
            price_gbp = (unit_price / 100).to_decimal() if hasattr(unit_price / 100, 'to_decimal') else f"£{unit_price/100:.2f}"

            html = f"""
            <h2>Your Order Has Been Approved! 🎉</h2>
            <p>Hi {o.customer_name},</p>
            <p>Great news! Your order <strong>{o.order_number}</strong> has been approved by our team.</p>

            <h3>Order Summary</h3>
            <ul>
              <li><strong>Product:</strong> {o.product_name} ({o.product_brand or 'N/A'})</li>
              <li><strong>Price:</strong> £{unit_price/100:.2f}</li>
              <li><strong>Payment Options:</strong> Klarna, Clearpay, Card, Apple Pay, Google Pay</li>
            </ul>

            <h3>Next Step</h3>
            """

            if stripe_link_url:
                html += f"""
                <p><a href="{stripe_link_url}" style="display:inline-block;padding:12px 24px;background:#0D0D0D;color:#F5C600;text-decoration:none;border-radius:4px;font-weight:bold">Pay Now with Instalments →</a></p>
                <p>Or copy this link: <code>{stripe_link_url}</code></p>
                """
            else:
                html += f"""
                <p>Your payment link is being prepared. You'll receive it shortly via email.</p>
                <p>If you don't receive it within 5 minutes, please contact us.</p>
                """

            html += f"""
            <hr>
            <p style="color:#666;font-size:12px;">
              Order #: {o.order_number}<br>
              Status: Approved & Ready to Pay<br>
              Lidle-By-Lidle Personal Shopper
            </p>
            """

            await send_email(o.customer_email, o.customer_name, subject, html)

        asyncio.create_task(_notify())

    log_action(db, current_user, "APPROVE_ORDER", "orders", order_id, {
        "unit_price": unit_price,
        "stripe_link": stripe_link_url or "not_generated"
    })

    result = order_to_dict(o)
    if stripe_link_url:
        result["stripe_payment_link"] = stripe_link_url

    return {"success": True, "order": result, "payment_link": stripe_link_url}


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
        "product_name": o.product_name, "product_brand": o.product_brand,
        "product_link": o.product_link, "product_variant": o.product_variant,
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
        Order.status.in_(["paid", "manual"])
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
            Order.fulfillment_status == "unfulfilled"
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
                msg = (f"📦 Your Lidle-By-Lidle order {od['order_number']} has shipped!"
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
                    product_name=meta.get("product_name") or "Product",
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
