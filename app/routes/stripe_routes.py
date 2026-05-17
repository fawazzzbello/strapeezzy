# app/routes/stripe_routes.py — Stripe payment intents only (webhook handled in main.py)
import os
from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.models.schemas import PaymentIntentCreate, PaymentIntentOut
from app.models.database import get_db, Product
import stripe

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
PRODUCT_PRICE = int(os.getenv("PRODUCT_PRICE_CENTS", "7900"))

router = APIRouter(prefix="/api/stripe", tags=["stripe"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/create-payment-intent", response_model=PaymentIntentOut)
@limiter.limit("20/minute")
async def create_payment_intent(request: Request, body: PaymentIntentCreate, db: Session = Depends(get_db)):
    if not stripe.api_key or stripe.api_key.startswith("sk_test_YOUR"):
        raise HTTPException(503, "Stripe not configured. Add STRIPE_SECRET_KEY to environment variables.")

    product = db.query(Product).filter(Product.name == body.product_name).first()
    if not product:
        raise HTTPException(400, f"Unknown product: {body.product_name}")

    price = product.price_cents

    try:
        intent = stripe.PaymentIntent.create(
            amount=price,
            currency="gbp",
            automatic_payment_methods={"enabled": True},
            receipt_email=body.customer_email,
            description=f"Lidle-By-Lidle Product — {body.product_name}",
            metadata={
                "product_name": body.product_name,
                "product_colorway": product.colorway or "",
                "customer_name": body.customer_name or "",
                "customer_email": body.customer_email or "",
                "customer_phone": body.customer_phone or "",
                "shipping_address": body.shipping_address or "",
            },
        )
        return PaymentIntentOut(client_secret=intent.client_secret, amount=price)
    except stripe.StripeError as e:
        raise HTTPException(400, str(e))


@router.get("/publishable-key")
async def get_publishable_key():
    """Returns the Stripe publishable key for the frontend."""
    pk = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    if not pk or pk.startswith("pk_test_YOUR"):
        return {"key": None, "configured": False}
    return {"key": pk, "configured": True}


@router.get("/health")
async def stripe_health():
    """Check Stripe API configuration and connectivity."""
    sk = os.getenv("STRIPE_SECRET_KEY", "")
    pk = os.getenv("STRIPE_PUBLISHABLE_KEY", "")

    if not sk or sk.startswith("sk_test_YOUR"):
        return {
            "status": "unconfigured",
            "message": "Stripe secret key not configured",
            "secret_configured": False,
            "publishable_configured": False,
        }

    if not pk or pk.startswith("pk_test_YOUR"):
        return {
            "status": "partially_configured",
            "message": "Stripe publishable key not configured",
            "secret_configured": True,
            "publishable_configured": False,
        }

    try:
        stripe.api_key = sk
        account = stripe.Account.retrieve()
        return {
            "status": "ok",
            "message": "Stripe is properly configured and connected",
            "secret_configured": True,
            "publishable_configured": True,
            "account_id": account.id,
            "account_email": account.email,
        }
    except stripe.StripeError as e:
        return {
            "status": "error",
            "message": f"Stripe API error: {str(e)}",
            "secret_configured": True,
            "publishable_configured": True,
            "error": str(e),
        }
