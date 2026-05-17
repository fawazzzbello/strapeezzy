# app/routes/admin_routes.py
import asyncio
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from sqlalchemy.orm import Session

from app.models.database import get_db, SiteConfig, ActivityLog, EmailCampaign, WaitlistEntry, AdminUser, Role
from app.models.schemas import ConfigUpdate, CampaignCreate, CampaignOut, LoginRequest, TokenResponse, UserOut
from app.middleware.auth import (
    get_current_user, require_roles, verify_password, create_access_token
)
from app.services.notifications import send_email, template_custom

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── LOGIN ──
@router.post("/login")
async def admin_login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(AdminUser).filter(
        AdminUser.username == body.username,
        AdminUser.is_active == True
    ).first()

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password",
        )

    user.last_login = datetime.now(timezone.utc)
    db.commit()

    token = create_access_token({"sub": str(user.id), "role": user.role, "username": user.username})

    log = ActivityLog(
        admin_id=user.id,
        admin_username=user.username,
        action="LOGIN",
        details=json.dumps({}),
        ip_address=request.client.host if request.client else None,
    )
    db.add(log)
    db.commit()

    return {
        "token": token,
        "access_token": token,
        "token_type": "bearer",
        "username": user.username,
        "role": user.role,
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
    }


# ── GET CURRENT ADMIN USER ──
@router.get("/me")
async def get_current_admin(
    current_user: AdminUser = Depends(get_current_user),
):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "is_active": current_user.is_active,
    }


DEFAULT_CONFIG = {
    "waitlist_count": "0",
    "maillist_count": "0",
    "launch_date": "2026-07-01",
    "site_title": "Strapeezzy — Pioneer Straps for the AP × Swatch Royalpop",
    "hero_headline_line1": "STRAP",
    "hero_headline_line2": "YOUR",
    "hero_headline_line3": "VIBE.",
    "hero_subtitle": "Premium Pioneer case-straps engineered exclusively for the AP × Swatch Royalpop. Eight bold colorways. One click. Zero compromise.",
    "strap_price": "79",
    "shipping_threshold": "150",
    "announcement_bar": "Free shipping on orders over $150 · Ships worldwide",
    "announcement_active": "1",
    "waitlist_active": "1",
    "store_active": "1",
    "sms_notifications": "1",
}


def get_all_config(db: Session) -> dict:
    rows = db.query(SiteConfig).all()
    cfg = dict(DEFAULT_CONFIG)
    cfg.update({r.key: r.value for r in rows})
    return cfg


def set_cfg(db: Session, key: str, value: str):
    row = db.query(SiteConfig).filter(SiteConfig.key == key).first()
    if row:
        row.value = str(value)
        row.updated_at = datetime.now(timezone.utc)
    else:
        row = SiteConfig(key=key, value=str(value))
        db.add(row)
    db.commit()


# ── GET CONFIG ──
@router.get("/config")
async def get_config(
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.VIEWER, Role.ADMIN, Role.SUPERADMIN)),
):
    return get_all_config(db)


# ── UPDATE CONFIG ──
@router.patch("/config")
async def update_config(
    body: ConfigUpdate,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    updates = body.model_dump(exclude_none=True)
    for key, value in updates.items():
        set_cfg(db, key, value)

    log = ActivityLog(
        admin_id=current_user.id,
        admin_username=current_user.username,
        action="UPDATE_CONFIG",
        entity="site_config",
        details=json.dumps(updates),
    )
    db.add(log)
    db.commit()

    return {"success": True, "updated": updates}


# ── EMAIL CAMPAIGNS ──

@router.get("/campaigns", response_model=list[CampaignOut])
async def list_campaigns(
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    campaigns = db.query(EmailCampaign).order_by(EmailCampaign.created_at.desc()).all()
    return [CampaignOut.model_validate(c) for c in campaigns]


@router.post("/campaigns")
async def send_campaign(
    body: CampaignCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    recipients = db.query(WaitlistEntry).all()
    if not recipients:
        return {"success": True, "sent": 0, "message": "No subscribers"}

    campaign = EmailCampaign(
        subject=body.subject,
        body=body.body,
        status="sending",
        created_by=current_user.id,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    campaign_id = campaign.id

    snap = [{"email": r.email, "name": r.name or ""} for r in recipients]

    log = ActivityLog(
        admin_id=current_user.id,
        admin_username=current_user.username,
        action="SEND_CAMPAIGN",
        entity="email_campaigns",
        entity_id=str(campaign_id),
        details=json.dumps({"recipient_count": len(snap), "subject": body.subject}),
    )
    db.add(log)
    db.commit()

    # Send in background
    subject_snap = body.subject
    body_snap = body.body

    async def _send_all():
        sent = 0
        failed = 0
        for r in snap:
            try:
                subject, html = template_custom(subject_snap, body_snap)
                ok = await send_email(r["email"], r["name"], subject, html)
                if ok:
                    sent += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.12)

        # Update campaign record
        from app.models.database import SessionLocal
        _db = SessionLocal()
        try:
            c = _db.query(EmailCampaign).filter(EmailCampaign.id == campaign_id).first()
            if c:
                c.sent_count = sent
                c.failed_count = failed
                c.status = "sent"
                c.sent_at = datetime.now(timezone.utc)
                _db.commit()
        finally:
            _db.close()

    background.add_task(_send_all)

    return {
        "success": True,
        "campaign_id": campaign_id,
        "recipientCount": len(snap),
        "message": f"Campaign started — sending to {len(snap)} subscribers in background",
    }


# ── USERS (admin management) ──
from app.models.schemas import UserCreate, UserUpdate

@router.get("/users")
async def list_admin_users(
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    users = db.query(AdminUser).order_by(AdminUser.created_at.desc()).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "full_name": u.full_name,
            "role": u.role,
            "is_active": u.is_active,
            "last_login": u.last_login.isoformat() if u.last_login else None,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


@router.post("/users")
async def create_admin_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.SUPERADMIN)),
):
    from app.middleware.auth import hash_password

    # Check uniqueness
    if db.query(AdminUser).filter(AdminUser.username == body.username).first():
        raise HTTPException(400, "Username already taken")
    if db.query(AdminUser).filter(AdminUser.email == body.email).first():
        raise HTTPException(400, "Email already registered")

    user = AdminUser(
        username=body.username,
        email=body.email,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    log = ActivityLog(
        admin_id=current_user.id,
        admin_username=current_user.username,
        action="CREATE_USER",
        entity="admin_users",
        entity_id=str(user.id),
        details=json.dumps({"username": user.username, "role": user.role}),
    )
    db.add(log)
    db.commit()

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "is_active": user.is_active,
    }


# ── ACTIVITY LOG ──
@router.get("/activity")
async def get_admin_activity(
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
    limit: int = 100,
):
    logs = db.query(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(limit).all()
    return [
        {
            "id": l.id,
            "admin_username": l.admin_username,
            "action": l.action,
            "entity": l.entity,
            "entity_id": l.entity_id,
            "details": l.details,
            "ip_address": l.ip_address,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in logs
    ]
