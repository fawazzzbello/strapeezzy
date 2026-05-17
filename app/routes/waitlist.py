# app/routes/waitlist.py
import asyncio
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timezone
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.models.database import get_db, WaitlistEntry, SiteConfig, ActivityLog
from app.models.schemas import WaitlistJoin, WaitlistOut, WaitlistCountsUpdate, CountsOut, NotifyAllRequest
from app.middleware.auth import get_current_user, require_roles, require_write, require_superadmin
from app.models.database import AdminUser, Role
from app.services.notifications import (
    send_email, send_sms,
    template_waitlist_confirm, template_waitlist_launch
)

router = APIRouter(prefix="/api/waitlist", tags=["waitlist"])
limiter = Limiter(key_func=get_remote_address)


# ── CONFIG HELPERS ──
def get_cfg(db: Session, key: str, default: str = "") -> str:
    row = db.query(SiteConfig).filter(SiteConfig.key == key).first()
    return row.value if row else default


def set_cfg(db: Session, key: str, value: str):
    row = db.query(SiteConfig).filter(SiteConfig.key == key).first()
    if row:
        row.value = str(value)
        row.updated_at = datetime.now(timezone.utc)
    else:
        row = SiteConfig(key=key, value=str(value))
        db.add(row)
    db.commit()


# ── PUBLIC: JOIN ──
@router.post("/join")
@limiter.limit("5/minute")
async def join_waitlist(request: Request, body: WaitlistJoin, background: BackgroundTasks, db: Session = Depends(get_db)):
    # Check duplicate
    exists = db.query(WaitlistEntry).filter(WaitlistEntry.email == body.email).first()
    if exists:
        raise HTTPException(409, "Already on the waitlist")

    entry = WaitlistEntry(
        email=body.email,
        name=body.name or "",
        phone=body.phone or "",
        notify_sms=body.notify_sms,
        source=body.source,
    )
    db.add(entry)
    db.commit()

    # Increment counts atomically
    wc = int(get_cfg(db, "waitlist_count", "0")) + 1
    ml = int(get_cfg(db, "maillist_count", "0")) + 1
    set_cfg(db, "waitlist_count", wc)
    set_cfg(db, "maillist_count", ml)

    position = wc

    # Fire-and-forget notifications
    async def _notify():
        subject, html = template_waitlist_confirm(body.name or "", position)
        await send_email(body.email, body.name, subject, html)
        if body.notify_sms and body.phone:
            await send_sms(
                body.phone,
                f"🎉 You're #{position} on the Lidle-By-Lidle waitlist! We'll text when Pioneer straps go live. lidle.com"
            )

    background.add_task(_notify)

    return {
        "success": True,
        "position": position,
        "waitlist_count": wc,
        "maillist_count": ml,
        "message": f"You're #{position} on the waitlist!",
    }


# ── PUBLIC: LIVE COUNTS ──
@router.get("/counts", response_model=CountsOut)
async def get_counts(db: Session = Depends(get_db)):
    return CountsOut(
        waitlist_count=int(get_cfg(db, "waitlist_count", "0")),
        maillist_count=int(get_cfg(db, "maillist_count", "0")),
        launch_date=get_cfg(db, "launch_date", "2026-07-01"),
        waitlist_active=get_cfg(db, "waitlist_active", "1") == "1",
    )


# ── ADMIN: LIST ──
@router.get("/")
async def list_waitlist(
    page: int = 1,
    limit: int = 100,
    search: str = "",
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.VIEWER, Role.ADMIN, Role.SUPERADMIN)),
):
    q = db.query(WaitlistEntry)
    if search:
        q = q.filter(
            (WaitlistEntry.email.ilike(f"%{search}%")) |
            (WaitlistEntry.name.ilike(f"%{search}%"))
        )
    total = q.count()
    entries = q.order_by(WaitlistEntry.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
    return {
        "entries": [WaitlistOut.model_validate(e) for e in entries],
        "total": total,
        "page": page,
        "limit": limit,
    }


# ── ADMIN: OVERRIDE COUNTS ──
@router.patch("/counts")
async def update_counts(
    body: WaitlistCountsUpdate,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    if body.waitlist_count is not None:
        set_cfg(db, "waitlist_count", body.waitlist_count)
    if body.maillist_count is not None:
        set_cfg(db, "maillist_count", body.maillist_count)

    log = ActivityLog(
        admin_id=current_user.id,
        admin_username=current_user.username,
        action="UPDATE_COUNTS",
        entity="site_config",
        entity_id="counts",
        details=str(body.model_dump(exclude_none=True)),
    )
    db.add(log)
    db.commit()

    return {
        "success": True,
        "waitlist_count": int(get_cfg(db, "waitlist_count", "0")),
        "maillist_count": int(get_cfg(db, "maillist_count", "0")),
    }


# ── ADMIN: NOTIFY ALL (launch blast) ──
@router.post("/notify-all")
async def notify_all(
    body: NotifyAllRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    entries = db.query(WaitlistEntry).filter(WaitlistEntry.notified == False).all()
    if not entries:
        return {"success": True, "sent": 0, "message": "No un-notified recipients"}

    # Snapshot the list for background task
    recipients = [{"email": e.email, "name": e.name, "phone": e.phone, "notify_sms": e.notify_sms} for e in entries]
    entry_ids = [e.id for e in entries]
    shop_url = body.shop_url

    # Mark as notified immediately
    for e in entries:
        e.notified = True
        e.notified_at = datetime.now(timezone.utc)
    db.commit()

    log = ActivityLog(
        admin_id=current_user.id,
        admin_username=current_user.username,
        action="NOTIFY_WAITLIST",
        entity="waitlist",
        entity_id="all",
        details=f"Notifying {len(recipients)} recipients",
    )
    db.add(log)
    db.commit()

    async def _blast():
        sent = 0
        sms_sent = 0
        for r in recipients:
            subject, html = template_waitlist_launch(r.get("name", ""), shop_url)
            ok = await send_email(r["email"], r.get("name"), subject, html)
            if ok:
                sent += 1
            if r.get("notify_sms") and r.get("phone"):
                await send_sms(r["phone"],
                    f"🚨 Lidle-By-Lidle is LIVE! Pioneer straps for the AP × Swatch Royalpop. Shop: {shop_url}")
                sms_sent += 1
            await asyncio.sleep(0.12)

    background.add_task(_blast)

    return {
        "success": True,
        "recipients": len(recipients),
        "message": f"Notifying {len(recipients)} recipients in background",
    }


# ── ADMIN: EXPORT CSV ──
@router.get("/export")
async def export_waitlist(
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    import csv, io
    from fastapi.responses import Response

    entries = db.query(WaitlistEntry).order_by(WaitlistEntry.created_at.asc()).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["#", "Email", "Name", "Phone", "SMS Opt-in", "Notified", "Source", "Joined (UTC)"])
    for i, e in enumerate(entries, 1):
        w.writerow([
            i, e.email, e.name or "", e.phone or "",
            "Yes" if e.notify_sms else "No",
            "Yes" if e.notified else "No",
            e.source or "",
            e.created_at.strftime("%Y-%m-%d %H:%M") if e.created_at else "",
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="lidle-waitlist.csv"'},
    )


# ── ADMIN: DELETE ENTRY ──
@router.delete("/{entry_id}", status_code=204)
async def delete_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    entry = db.query(WaitlistEntry).filter(WaitlistEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Entry not found")
    db.delete(entry)
    db.commit()
