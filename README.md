# Strapeezzy — FastAPI Backend

## Stack

| Layer | Tech |
|-------|------|
| Framework | FastAPI + Uvicorn |
| Database | SQLite (dev) / PostgreSQL (prod) via SQLAlchemy |
| Auth | JWT (python-jose) + bcrypt (passlib) |
| Payments | Stripe Python SDK — Payment Element (cards, Klarna, Clearpay, Apple/Google Pay) |
| Email | Brevo SMTP via smtplib (300/day free) |
| SMS | Twilio Python SDK |
| Rate limiting | slowapi |
| Deploy | Railway (recommended) or Render |

## Project Structure

```
strapeezzy/
├── main.py                    ← FastAPI app, lifespan, seed, webhook
├── requirements.txt
├── Procfile                   ← start command (uvicorn main:app --host 0.0.0.0 --port $PORT)
├── railway.toml
├── .env.example
├── app/
│   ├── models/
│   │   ├── database.py        ← SQLAlchemy models + DB init
│   │   └── schemas.py         ← Pydantic schemas
│   ├── middleware/
│   │   └── auth.py            ← JWT auth + RBAC
│   ├── routes/
│   │   ├── admin_routes.py    ← Site config, campaigns, image upload
│   │   ├── orders.py          ← Orders, fulfillment, stats
│   │   ├── products.py        ← Product CRUD + image upload
│   │   ├── stripe_routes.py   ← Payment intents
│   │   └── waitlist.py        ← Join, counts, notify-all, CSV export
│   └── services/
│       └── notifications.py   ← Brevo SMTP + Twilio SMS
├── admin/
│   └── index.html             ← Admin SPA (served at /admin)
└── public/
    └── index.html             ← Customer-facing landing page
```

## Deploy to Railway (recommended)

```bash
npm i -g @railway/cli
railway login
railway init
railway up
```

Add a PostgreSQL plugin in the Railway dashboard — it sets `DATABASE_URL` automatically.

Set environment variables in the Railway dashboard (or via CLI):

```bash
railway variables set JWT_SECRET=<random-64-char-string>
railway variables set STRIPE_SECRET_KEY=sk_live_...
railway variables set STRIPE_PUBLISHABLE_KEY=pk_live_...
railway variables set STRIPE_WEBHOOK_SECRET=whsec_...
railway variables set BREVO_SMTP_USER=you@example.com
railway variables set BREVO_SMTP_PASS=<brevo-smtp-key>
railway variables set FROM_EMAIL=hello@strapeezzy.com
railway variables set INIT_ADMIN_USERNAME=admin
railway variables set INIT_ADMIN_PASSWORD=<strong-password>
```

After deploying, the app seeds the database automatically on first boot:
- Creates the superadmin from `INIT_ADMIN_USERNAME` / `INIT_ADMIN_PASSWORD`
- Upserts the 8 canonical Royal Pop products

## Deploy to Render (alternative)

1. Push to GitHub, create a new **Web Service** on render.com
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add all env vars in the Render dashboard

## Accessing the App

| Path | Description |
|------|-------------|
| `/` | Customer landing page |
| `/admin` | Admin dashboard |
| `/api/docs` | Swagger UI |
| `/api/health` | Health check |

Default admin login: set via `INIT_ADMIN_USERNAME` / `INIT_ADMIN_PASSWORD` env vars.

---

## Service Setup

### Stripe

1. Create account at stripe.com
2. Copy **Secret key** → `STRIPE_SECRET_KEY`, **Publishable key** → `STRIPE_PUBLISHABLE_KEY`
3. Create a webhook endpoint pointing to `https://your-domain/api/stripe/webhook`
   - Event to subscribe: `payment_intent.succeeded`
   - Copy the **Signing secret** → `STRIPE_WEBHOOK_SECRET`
4. Enable payment methods in Stripe Dashboard → Settings → Payment methods
   (Klarna, Clearpay/Afterpay, Apple Pay, Google Pay are shown automatically via the Payment Element)

### Brevo SMTP (300 emails/day free)

1. Sign up at app.brevo.com
2. Account Settings → SMTP & API → Generate SMTP key
3. Set `BREVO_SMTP_USER` (your login email) and `BREVO_SMTP_PASS` (the generated key)
4. Verify your sender address in Brevo → Senders & IPs → Senders (required or emails bounce)
5. Alternative env var names `BREVO_USER` / `BREVO_PASS` are also accepted

### Twilio SMS (~$15 free trial credit)

1. Sign up at twilio.com/try-twilio
2. Get a trial phone number
3. Set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`

---

## User Roles & Permissions

| Action | viewer | admin | superadmin |
|--------|--------|-------|------------|
| View orders, stats, waitlist, activity log | ✅ | ✅ | ✅ |
| Create/fulfill orders, edit config, send campaigns | ❌ | ✅ | ✅ |
| Notify waitlist, export CSV | ❌ | ✅ | ✅ |
| Create/edit/delete admin users | ❌ | ❌ | ✅ |
| Delete orders | ❌ | ❌ | ✅ |

---

## API Reference

### Public

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/config/public` | Site config for landing page |
| `GET` | `/api/products/` | List active products |
| `POST` | `/api/waitlist/join` | Join waitlist |
| `GET` | `/api/waitlist/counts` | Live waitlist count |
| `POST` | `/api/stripe/create-payment-intent` | Start checkout |
| `POST` | `/api/stripe/webhook` | Stripe webhook |
| `GET` | `/api/health` | Health check |

### Authenticated (Bearer token from `POST /api/admin/login`)

| Method | Path | Min role | Description |
|--------|------|---------|-------------|
| `GET` | `/api/orders/stats` | viewer | Dashboard stats |
| `GET` | `/api/orders` | viewer | List orders |
| `GET` | `/api/orders/:id` | viewer | Order detail |
| `POST` | `/api/orders/manual` | admin | Create manual order |
| `PATCH` | `/api/orders/:id/fulfill` | admin | Update fulfillment + notify customer |
| `PATCH` | `/api/orders/:id/status` | admin | Update payment status |
| `DELETE` | `/api/orders/:id` | superadmin | Delete order |
| `GET` | `/api/waitlist/` | viewer | List waitlist entries |
| `GET` | `/api/waitlist/export` | admin | Download waitlist as CSV |
| `PATCH` | `/api/waitlist/counts` | admin | Override displayed counts |
| `POST` | `/api/waitlist/notify-all` | admin | Send launch email + SMS blast |
| `DELETE` | `/api/waitlist/:id` | admin | Remove entry |
| `GET` | `/api/admin/config` | viewer | Full site config |
| `PATCH` | `/api/admin/config` | admin | Update site config |
| `GET` | `/api/admin/campaigns` | admin | List email campaigns |
| `POST` | `/api/admin/campaigns` | admin | Send email campaign |
| `GET` | `/api/products/admin/all` | admin | List all products (incl. inactive) |
| `POST` | `/api/products/admin` | admin | Create product |
| `PATCH` | `/api/products/admin/:id` | admin | Update product |
| `DELETE` | `/api/products/admin/:id` | superadmin | Delete product |
| `GET` | `/api/admin/users` | admin | List admin users |
| `POST` | `/api/admin/users` | superadmin | Create admin user |
| `GET` | `/api/admin/activity` | admin | Activity log |

---

## Database

SQLite is used automatically when `DATABASE_URL` is not set (local dev / single-dyno deploys).
Switch to PostgreSQL by setting:

```
DATABASE_URL=postgresql://user:password@host:5432/strapeezzy
```

No code changes required — SQLAlchemy handles both.
