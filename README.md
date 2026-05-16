# Strapeezzy — Python / FastAPI Backend

## Stack
| Layer | Tech |
|-------|------|
| Framework | FastAPI + Uvicorn |
| Database | SQLite (dev) / PostgreSQL (prod) via SQLAlchemy |
| Auth | JWT (python-jose) + bcrypt (passlib) |
| Payments | Stripe Python SDK |
| Email | Brevo SMTP via smtplib (300/day free) |
| SMS | Twilio Python SDK |
| Rate limiting | slowapi |
| Deploy | Railway or Render (free tier) |

## Project Structure
```
strapeezzy-py/
├── main.py                    ← FastAPI app, lifespan, routing
├── requirements.txt
├── Procfile                   ← Railway/Render start command
├── railway.toml               ← Railway config
├── render.yaml                ← Render config
├── .env.example               ← Copy to .env
├── app/
│   ├── models/
│   │   ├── database.py        ← SQLAlchemy models + DB init
│   │   └── schemas.py         ← Pydantic request/response schemas
│   ├── middleware/
│   │   └── auth.py            ← JWT auth + RBAC dependency factories
│   ├── routes/
│   │   ├── auth.py            ← Login, user CRUD, activity log
│   │   ├── orders.py          ← Orders, fulfillment, manual orders
│   │   ├── waitlist.py        ← Join, counts, notify-all
│   │   ├── stripe_routes.py   ← Payment intents + webhooks
│   │   └── admin_routes.py    ← Site config, email campaigns
│   └── services/
│       └── notifications.py   ← Brevo SMTP + Twilio SMS
├── admin/
│   └── index.html             ← Admin SPA
└── public/
    └── index.html             ← Landing page (copy strapeezzy.html here)
```

## Quick Start

### 1. Install Python deps
```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure
```bash
cp .env.example .env
# Edit .env with your real API keys
```

### 3. Place the landing page
```bash
cp /path/to/strapeezzy.html public/index.html
cp /path/to/strapeezzy-admin.html admin/index.html
```

### 4. Run
```bash
uvicorn main:app --reload --port 8000
```

### 5. Access
- **Landing page:** http://localhost:8000
- **Admin panel:** http://localhost:8000/admin
- **API docs (Swagger):** http://localhost:8000/api/docs
- **Default login:** `admin` / `strapeezzy2024!` ← CHANGE in .env

---

## User Roles & Permissions

| Action | viewer | admin | superadmin |
|--------|--------|-------|------------|
| View orders & stats | ✅ | ✅ | ✅ |
| View waitlist | ✅ | ✅ | ✅ |
| View activity log | ✅ | ✅ | ✅ |
| Create/fulfill orders | ❌ | ✅ | ✅ |
| Edit site config | ❌ | ✅ | ✅ |
| Send email campaigns | ❌ | ✅ | ✅ |
| Notify waitlist | ❌ | ✅ | ✅ |
| Create admin users | ❌ | ❌ | ✅ |
| Edit/delete admin users | ❌ | ❌ | ✅ |
| Delete orders | ❌ | ❌ | ✅ |
| Create superadmin | ❌ | ❌ | ✅ |

---

## Service Setup

### Stripe
```bash
# Install Stripe CLI for local webhook testing
stripe listen --forward-to localhost:8000/api/stripe/webhook
# Copy the webhook secret → STRIPE_WEBHOOK_SECRET in .env
```
Events to handle: `payment_intent.succeeded`, `payment_intent.payment_failed`

### Brevo SMTP (300 emails/day free)
1. Sign up at https://app.brevo.com
2. Account Settings → SMTP & API → Generate SMTP key
3. Add to `.env`: `BREVO_SMTP_USER` (your login email), `BREVO_SMTP_PASS` (the key)

### Twilio SMS (~$15 free trial credit)
1. Sign up at https://www.twilio.com/try-twilio
2. Get a trial number
3. Add `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` to `.env`

---

## Deploy to Railway (recommended — free tier)

```bash
# Install Railway CLI
npm i -g @railway/cli

# Login and deploy
railway login
railway init
railway up

# Set environment variables
railway variables set JWT_SECRET=your-secret
railway variables set STRIPE_SECRET_KEY=sk_live_...
# ... add all other .env vars in Railway dashboard
```
Railway auto-detects Python, uses `Procfile` for start command.

## Deploy to Render (alternative free tier)

1. Push code to GitHub
2. Create new **Web Service** on render.com
3. Connect your repo
4. Build command: `pip install -r requirements.txt`
5. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. Add all env vars in Render dashboard

---

## API Reference (full docs at /api/docs)

### Public
| Method | Path | Rate limit | Description |
|--------|------|-----------|-------------|
| POST | /api/waitlist/join | 20/15min | Join waitlist |
| GET | /api/waitlist/counts | 100/15min | Live counts |
| POST | /api/stripe/create-payment-intent | 100/15min | Create payment |
| POST | /api/stripe/webhook | — | Stripe events |
| GET | /api/health | — | Health check |

### Authenticated (Bearer token from /api/auth/login)
| Method | Path | Min role | Description |
|--------|------|---------|-------------|
| POST | /api/auth/login | — | Get JWT token |
| GET | /api/auth/me | any | Current user |
| GET | /api/auth/users | admin | List users |
| POST | /api/auth/users | superadmin | Create user |
| PATCH | /api/auth/users/:id | superadmin | Update user |
| DELETE | /api/auth/users/:id | superadmin | Delete user |
| GET | /api/auth/activity | admin | Activity log |
| GET | /api/orders/stats | viewer | Dashboard stats |
| GET | /api/orders | viewer | List orders |
| GET | /api/orders/:id | viewer | Order detail |
| POST | /api/orders/manual | admin | Create manual order |
| PATCH | /api/orders/:id/fulfill | admin | Update fulfillment |
| PATCH | /api/orders/:id/status | admin | Update status |
| DELETE | /api/orders/:id | superadmin | Delete order |
| GET | /api/waitlist | viewer | List waitlist |
| PATCH | /api/waitlist/counts | admin | Override counts |
| POST | /api/waitlist/notify-all | admin | Send launch blast |
| DELETE | /api/waitlist/:id | admin | Remove entry |
| GET | /api/admin/config | viewer | Get site config |
| PATCH | /api/admin/config | admin | Update site config |
| GET | /api/admin/campaigns | admin | List campaigns |
| POST | /api/admin/campaigns | admin | Send campaign |

---

## Connecting the Landing Page

In `public/index.html`, update the API base URL and Stripe key:

```javascript
// Change this to your deployed Railway/Render URL
const API_BASE = 'https://your-app.railway.app';

// Your Stripe publishable key
const STRIPE_PK = 'pk_live_YOUR_KEY';
```

The landing page calls:
- `POST ${API_BASE}/api/waitlist/join` — waitlist form
- `GET ${API_BASE}/api/waitlist/counts` — live counter (polls every 30s)
- `POST ${API_BASE}/api/stripe/create-payment-intent` — checkout

---

## Switching to PostgreSQL (production)

```bash
# In .env, change:
DATABASE_URL=postgresql://user:password@host:5432/strapeezzy

# On Railway, add a PostgreSQL plugin and it auto-sets DATABASE_URL
```
No code changes needed — SQLAlchemy handles both.
