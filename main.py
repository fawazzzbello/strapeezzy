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
            pwd = os.getenv("INIT_ADMIN_PASSWORD", "strapeezzy2024!")[:72]
            admin = AdminUser(
                username=os.getenv("INIT_ADMIN_USERNAME", "admin"),
                email=os.getenv("INIT_ADMIN_EMAIL", "admin@strapeezzy.com"),
                full_name="Super Admin",
                password_hash=hash_password(pwd),
                role=Role.SUPERADMIN,
            )
            db.add(admin)
            db.commit()
            print(f"✅ Superadmin: {admin.username}")

        defaults = {
            "waitlist_count": "0", "maillist_count": "0", "launch_date": "2026-07-01",
            "site_title": "Strapeezzy — Pioneer Straps for AP × Swatch Royalpop",
            "hero_headline_line1": "STRAP", "hero_headline_line2": "YOUR", "hero_headline_line3": "VIBE.",
            "hero_subtitle": "Premium Pioneer case-straps for the AP × Swatch Royalpop. Eight colorways.",
            "strap_price": "79", "shipping_threshold": "150",
            "announcement_bar": "Free shipping on orders over $150 · Ships worldwide",
            "announcement_active": "1", "waitlist_active": "1", "store_active": "1", "sms_notifications": "1", "waitlist_fee": "0",
        }
        for key, value in defaults.items():
            if not db.query(SiteConfig).filter(SiteConfig.key == key).first():
                db.add(SiteConfig(key=key, value=value))
        db.commit()

        if db.query(Product).count() == 0:
            products_seed = [
                {
                    "sku": "RPPOP-LIME",
                    "name": "Royal Pop Lime Frost",
                    "description": "Bioceramic case in acid lime with a contrasting sky-blue octagonal bezel. The lime dial features a classic Petit Tapisserie pattern with ice-blue baton indices. Paired with a matching lime rubber strap, this colorway is built for those who refuse to go unnoticed.",
                    "price_cents": 7900,
                    "colorway": "Lime / Sky Blue",
                    "image_url": "/images/img-0.jpg",
                    "stock_quantity": 48,
                },
                {
                    "sku": "RPPOP-FORET",
                    "name": "Royal Pop Forêt Verte",
                    "description": "A monochromatic study in green. Case, bezel, dial, and strap all rendered in the same bold forest green bioceramic. Luminous green hands disappear into the dial until the light catches them just right. Pure, intentional, unapologetic.",
                    "price_cents": 7900,
                    "colorway": "All Green",
                    "image_url": "/images/img-1.jpg",
                    "stock_quantity": 35,
                },
                {
                    "sku": "RPPOP-CONFETTI",
                    "name": "Royal Pop Confetti",
                    "description": "White bioceramic case and strap anchor a riot of rainbow colour. Eight multicoloured screws on the bezel, multicoloured baton indices, and a teal second hand make every glance a celebration. The only watch that brings the party with it.",
                    "price_cents": 7900,
                    "colorway": "White / Rainbow",
                    "image_url": "/images/img-2.jpg",
                    "stock_quantity": 60,
                },
                {
                    "sku": "RPPOP-CIEL",
                    "name": "Royal Pop Ciel Nocturne",
                    "description": "Powder-blue case and strap cradle a deep navy dial with white baton indices. A small seconds sub-dial adds a dressy touch. Understated in daylight, striking after dark.",
                    "price_cents": 7900,
                    "colorway": "Baby Blue / Navy",
                    "image_url": "/images/img-3.jpg",
                    "stock_quantity": 42,
                },
                {
                    "sku": "RPPOP-ONYX",
                    "name": "Royal Pop Onyx Blanc",
                    "description": "Matte black bioceramic case and strap with a stark white octagonal bezel. The black dial with white indices channels the stark geometry of the original Royal Oak. The most serious colorway in the lineup — and the most versatile.",
                    "price_cents": 7900,
                    "colorway": "Black / White",
                    "image_url": "/images/img-4.jpg",
                    "stock_quantity": 55,
                },
                {
                    "sku": "RPPOP-CARNIVAL-PW",
                    "name": "Royal Pop Carnival Pocket",
                    "description": "Pocket watch format in teal, yellow, and pink — three colours that have no business looking this good together. The teal Petit Tapisserie dial features a pink small-seconds and yellow baton markers. The open caseback reveals the movement decorated with graphic Royal Pop artwork. Worn on a braided pink cord.",
                    "price_cents": 24900,
                    "colorway": "Teal / Yellow / Pink",
                    "image_url": "/images/img-5.jpg",
                    "stock_quantity": 20,
                },
                {
                    "sku": "RPPOP-ROSE-PW",
                    "name": "Royal Pop Rose Quartz Pocket",
                    "description": "Pocket watch in blush pink and crimson. The soft pink dial with matching indices sits behind a bold crimson bezel. The display caseback shows the movement under a Royal Pop graphic in matching pink tones. Suspended from a braided blush leather cord.",
                    "price_cents": 24900,
                    "colorway": "Blush Pink / Crimson",
                    "image_url": "/images/img-6.jpg",
                    "stock_quantity": 18,
                },
                {
                    "sku": "RPPOP-NAUTILUS",
                    "name": "Royal Pop Nautilus",
                    "description": "Navy bioceramic case, bezel, and strap with eight vivid orange octagonal screws. The navy dial features orange baton indices and orange hands that pop against the deep blue. Inspired by deep-sea precision instruments, this is the sports colorway of the collection.",
                    "price_cents": 7900,
                    "colorway": "Navy / Orange",
                    "image_url": "/images/img-7.jpg",
                    "stock_quantity": 38,
                },
                {
                    "sku": "RPPOP-TROPICANA",
                    "name": "Royal Pop Tropicana",
                    "description": "Yellow strap and case meet a candy-pink middle band and bezel. The turquoise-teal dial is anchored by a pink small-seconds counter with yellow hand. A tri-colour collision that captures poolside energy at its most unfiltered.",
                    "price_cents": 7900,
                    "colorway": "Yellow / Pink / Teal",
                    "image_url": "/images/img-8.jpg",
                    "stock_quantity": 30,
                },
                {
                    "sku": "RPPOP-FLAMINGO",
                    "name": "Royal Pop Flamingo",
                    "description": "Blush-pink bioceramic case and strap with a hot-pink octagonal bezel. The blush dial features matching pink indices and a crimson seconds hand. Feminine without being soft, bold without being loud. The most requested colorway before launch.",
                    "price_cents": 7900,
                    "colorway": "Blush / Hot Pink",
                    "image_url": "/images/img-9.jpg",
                    "stock_quantity": 45,
                },
            ]
            for pd in products_seed:
                db.add(Product(**pd))
            db.commit()
            print(f"✅ {len(products_seed)} products seeded")

        print("✅ DB seeded")
    except Exception as e:
        print(f"⚠️ Seed error (non-fatal): {e}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_db()
    print("🚀 Strapeezzy ready")
    yield


limiter = Limiter(key_func=get_remote_address)
app = FastAPI(
    title="Strapeezzy API", version="1.0.0",
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
    # For API responses, cache for 5 minutes
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "public, max-age=300"
    return response

# ── ROUTERS ──
from app.routes.auth import router as auth_router
from app.routes.waitlist import router as waitlist_router
from app.routes.orders import router as orders_router
from app.routes.admin_routes import router as admin_router
from app.routes.stripe_routes import router as stripe_router
from app.routes.products import router as products_router

app.include_router(auth_router)
app.include_router(waitlist_router)
app.include_router(orders_router)
app.include_router(admin_router)
app.include_router(stripe_router)
app.include_router(products_router)


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
                    product_name=meta.get("product_name") or "Pioneer Strap",
                    product_variant=meta.get("product_variant") or "",
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
    return {"status": "ok", "service": "strapeezzy"}


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
    f = PUBLIC_DIR / "index.html"
    if f.exists():
        return FileResponse(str(f))
    return JSONResponse({"message": "Strapeezzy API ✅", "docs": "/api/docs", "health": "/api/health", "admin": "/admin"})
