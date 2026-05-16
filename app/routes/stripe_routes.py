# app/routes/stripe_routes.py — Stripe payment intents only (webhook handled in main.py)
import os
from fastapi import APIRouter, HTTPException
from app.models.schemas import PaymentIntentCreate, PaymentIntentOut
import stripe

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
PRODUCT_PRICE = int(os.getenv("PRODUCT_PRICE_CENTS", "7900"))

router = APIRouter(prefix="/api/stripe", tags=["stripe"])

PRODUCTS = {
    "OTG ROZ":      {"price": PRODUCT_PRICE, "variant": "Pink / Yellow · Savonette"},
    "Otto Rosso":   {"price": PRODUCT_PRICE, "variant": "Crimson / Blush · Lépine"},
    "Green Eight":  {"price": PRODUCT_PRICE, "variant": "Forest Green · Lépine"},
    "Huit Blanc":   {"price": PRODUCT_PRICE, "variant": "White Multicolor · Lépine"},
    "Blaue Acht":   {"price": PRODUCT_PRICE, "variant": "Sky Blue / Navy · Lépine"},
    "Ocho Negro":   {"price": PRODUCT_PRICE, "variant": "Black / White · Lépine"},
    "Lan Ba":       {"price": PRODUCT_PRICE, "variant": "Navy / Orange · Savonette"},
    "Orenji Hachi": {"price": PRODUCT_PRICE, "variant": "Navy / Orange · Lépine"},
}


@router.post("/create-payment-intent", response_model=PaymentIntentOut)
async def create_payment_intent(body: PaymentIntentCreate):
    if not stripe.api_key or stripe.api_key.startswith("sk_test_YOUR"):
        raise HTTPException(503, "Stripe not configured. Add STRIPE_SECRET_KEY to environment variables.")

    product = PRODUCTS.get(body.product_name)
    if not product:
        raise HTTPException(400, f"Unknown product: {body.product_name}")

    try:
        intent = stripe.PaymentIntent.create(
            amount=product["price"],
            currency="usd",
            receipt_email=body.customer_email,
            description=f"Strapeezzy Pioneer Strap — {body.product_name}",
            metadata={
                "product_name": body.product_name,
                "product_variant": product["variant"],
                "customer_name": body.customer_name or "",
                "customer_email": body.customer_email or "",
                "customer_phone": body.customer_phone or "",
            },
        )
        return PaymentIntentOut(client_secret=intent.client_secret, amount=product["price"])
    except stripe.StripeError as e:
        raise HTTPException(400, str(e))


@router.get("/publishable-key")
async def get_publishable_key():
    """Returns the Stripe publishable key for the frontend."""
    pk = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    if not pk or pk.startswith("pk_test_YOUR"):
        return {"key": None, "configured": False}
    return {"key": pk, "configured": True}
