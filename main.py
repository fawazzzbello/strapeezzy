# main.py — Strapeezzy FastAPI Backend
import os
import json
import random
import string
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from dotenv import load_dotenv

load_dotenv()

from app.models.database import init_db, SessionLocal, AdminUser, SiteConfig, Role
from app.middleware.auth import hash_password


def seed_db():
    from app.models.database import Product
    db = SessionLocal()
    try:
        if db.query(AdminUser).count() == 0:
            pwd = os.getenv("INIT_ADMIN_PASSWORD", "lidle2024!")[:72]
            admin = AdminUser(
                username=os.getenv("INIT_ADMIN_USERNAME", "admin"),
                email=os.getenv("INIT_ADMIN_EMAIL", "admin@lidle.com"),
                full_name="Super Admin",
                password_hash=hash_password(pwd),
                role=Role.SUPERADMIN,
            )
            db.add(admin)
            db.commit()
            print(f"✅ Superadmin: {admin.username}")

        defaults = {
            "waitlist_count": "0", "maillist_count": "0", "launch_date": "2026-07-01",
            "site_title": "Lidle-By-Lidle — Personal Shopper Store",
            "hero_headline_line1": "LIDLE", "hero_headline_line2": "BY", "hero_headline_line3": "LIDLE",
            "hero_subtitle": "Your personal shopper marketplace. Buy premium products in easy instalments.",
            "shipping_threshold": "150",
            "announcement_bar": "Welcome to Lidle-By-Lidle — Personal shopping made easy",
            "announcement_active": "1", "waitlist_active": "0", "store_active": "1", "sms_notifications": "0", "waitlist_fee": "0",
            "hero_slide_interval": "3000", "logo_type": "text", "logo_text": "lidle", "logo_image_url": "",
            "hero_badge": "SHOP SMART", "hero_cta1_text": "Browse Deals", "hero_cta2_text": "Submit Order",
            "nav_btn_text": "BROWSE", "nav_link1_text": "SHOP", "nav_link2_text": "HOW IT WORKS",
            "products_title": "Featured Deals", "waitlist_title": "Join the Waitlist",
            "waitlist_description": "Be the first to know when we launch. Get exclusive early-access pricing.",
            "waitlist_btn_text": "Join Waitlist",
        }
        for key, value in defaults.items():
            if not db.query(SiteConfig).filter(SiteConfig.key == key).first():
                db.add(SiteConfig(key=key, value=value))
        db.commit()

        # No seed products for personal shopper - admins will post them
        canonical_skus = set()
        products_seed = []

        print("✅ DB seeded")
    except Exception as e:
        print(f"⚠️ Seed error (non-fatal): {e}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    jwt_secret = os.getenv("JWT_SECRET", "change-this-secret")
    if jwt_secret in ("change-this-secret", "your-super-secret-jwt-key-change-me", ""):
        print("⚠️  WARNING: JWT_SECRET is not set or is using an insecure default. Set a strong random secret before launch!")
    init_db()
    seed_db()
    print("🚀 Lidle-By-Lidle ready")
    yield


limiter = Limiter(key_func=get_remote_address)
app = FastAPI(
    title="Lidle-By-Lidle API", version="1.0.0",
    lifespan=lifespan, docs_url="/api/docs", redoc_url="/api/redoc",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── PERFORMANCE MIDDLEWARE ──
from fastapi.middleware.gzip import GZipMiddleware

app.add_middleware(GZipMiddleware, minimum_size=1000)

@app.middleware("http")
async def add_performance_headers(request: Request, call_next):
    response = await call_next(request)
    # Enable compression and caching
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Cache-Control"] = "public, max-age=3600"
    # API responses must never be cached so admin edits are reflected immediately
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# ── ROUTERS ──
from app.routes.auth import router as auth_router
from app.routes.waitlist import router as waitlist_router
from app.routes.orders import router as orders_router
from app.routes.admin_routes import router as admin_router
from app.routes.stripe_routes import router as stripe_router
from app.routes.products import router as products_router
from app.routes.media import router as media_router

app.include_router(auth_router)
app.include_router(waitlist_router)
app.include_router(orders_router)
app.include_router(admin_router)
app.include_router(stripe_router)
app.include_router(products_router)
app.include_router(media_router)


# ── STRIPE WEBHOOK (raw body) ──
@app.post("/api/stripe/webhook", include_in_schema=False)
async def stripe_webhook_endpoint(request: Request):
    import stripe as stripe_lib
    from app.models.database import Order
    from app.services.notifications import send_email, template_order_confirm

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    try:
        if webhook_secret and not webhook_secret.startswith("whsec_YOUR"):
            event = stripe_lib.Webhook.construct_event(payload, sig, webhook_secret)
        else:
            event = json.loads(payload)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    if event.get("type") == "payment_intent.succeeded":
        pi = event["data"]["object"]
        meta = pi.get("metadata", {})
        db = SessionLocal()
        try:
            if not db.query(Order).filter(Order.stripe_payment_intent == pi["id"]).first():
                ts = str(int(datetime.now().timestamp()))[-6:]
                rnd = ''.join(random.choices(string.digits, k=3))
                o = Order(
                    order_number=f"SZ-{ts}-{rnd}",
                    stripe_payment_intent=pi["id"],
                    customer_name=meta.get("customer_name") or "Customer",
                    customer_email=meta.get("customer_email") or "",
                    customer_phone=meta.get("customer_phone") or "",
                    shipping_address=meta.get("shipping_address") or "",
                    product_name=meta.get("product_name") or "Pioneer Strap",
                    product_variant=meta.get("product_colorway") or meta.get("product_variant") or "",
                    quantity=1, unit_price=pi["amount"], total_amount=pi["amount"],
                    currency=pi.get("currency", "usd"),
                    status="paid", fulfillment_status="unfulfilled",
                )
                db.add(o)
                db.commit()
                db.refresh(o)
                od = {k: getattr(o, k) for k in ["order_number","customer_name","customer_email","customer_phone","product_name","product_variant","quantity","total_amount"]}
                if od["customer_email"]:
                    subject, html = template_order_confirm(od)
                    asyncio.create_task(send_email(od["customer_email"], od["customer_name"], subject, html))
        finally:
            db.close()

    return JSONResponse({"received": True})


# ── HEALTH ──
@app.get("/api/health", include_in_schema=False)
async def health():
    return {"status": "ok", "service": "lidle"}


# ── INIT ADMIN (first-time setup) ──
@app.post("/api/init-admin", include_in_schema=False)
async def init_admin(
    username: str = "admin",
    password: str = "strapeezzy2024!",
    email: str = "admin@strapeezzy.com",
):
    db = SessionLocal()
    try:
        # Check if admin already exists
        if db.query(AdminUser).count() > 0:
            return {"message": "Admin user already exists"}

        admin = AdminUser(
            username=username,
            email=email,
            full_name="Super Admin",
            password_hash=hash_password(password[:72]),  # Bcrypt limit
            role=Role.SUPERADMIN,
        )
        db.add(admin)
        db.commit()
        return {"success": True, "username": username, "message": "Admin user created"}
    except Exception as e:
        return {"error": str(e)}
    finally:
        db.close()


# ── STATIC / SPA ──
import pathlib
PUBLIC_DIR = pathlib.Path(__file__).parent / "public"
ADMIN_DIR = pathlib.Path(__file__).parent / "admin"

# Mount static files (images, CSS, JS)
if (PUBLIC_DIR / "images").exists():
    app.mount("/images", StaticFiles(directory=str(PUBLIC_DIR / "images")), name="images")

@app.get("/admin", include_in_schema=False)
@app.get("/admin/{path:path}", include_in_schema=False)
async def serve_admin(path: str = ""):
    f = ADMIN_DIR / "index.html"
    return FileResponse(str(f)) if f.exists() else JSONResponse({"error": "Admin not found"}, 404)


@app.get("/", include_in_schema=False)
@app.get("/{path:path}", include_in_schema=False)
async def serve_frontend(path: str = ""):
    if path.startswith("api"):
        return JSONResponse({"error": "Not found"}, status_code=404)
    f = PUBLIC_DIR / "index.html"
    if f.exists():
        return FileResponse(str(f))
    return JSONResponse({"message": "Lidle-By-Lidle API ✅", "docs": "/api/docs", "health": "/api/health", "admin": "/admin"})
