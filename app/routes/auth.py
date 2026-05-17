# app/routes/auth.py
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import json
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.models.database import get_db, AdminUser, ActivityLog, Role
from app.models.schemas import LoginRequest, TokenResponse, UserCreate, UserUpdate, UserOut
from app.middleware.auth import (
    verify_password, hash_password, create_access_token,
    get_current_user, require_roles, require_write, require_superadmin
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


def log_action(db: Session, user: AdminUser, action: str, entity: str = None,
               entity_id: str = None, details: dict = None, ip: str = None):
    entry = ActivityLog(
        admin_id=user.id,
        admin_username=user.username,
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id else None,
        details=json.dumps(details or {}),
        ip_address=ip,
    )
    db.add(entry)
    db.commit()


# ── LOGIN ──
@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(AdminUser).filter(
        AdminUser.username == body.username,
        AdminUser.is_active == True
    ).first()

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    user.last_login = datetime.now(timezone.utc)
    db.commit()

    token = create_access_token({"sub": str(user.id), "role": user.role, "username": user.username})

    log_action(db, user, "LOGIN", "auth", str(user.id), {}, request.client.host)

    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


# ── GET CURRENT USER ──
@router.get("/me", response_model=UserOut)
async def me(current_user: AdminUser = Depends(get_current_user)):
    return UserOut.model_validate(current_user)


# ── LIST USERS (admin+) ──
@router.get("/users", response_model=list[UserOut])
async def list_users(
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    users = db.query(AdminUser).order_by(AdminUser.created_at.desc()).all()
    return [UserOut.model_validate(u) for u in users]


# ── CREATE USER (superadmin only) ──
@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    request: Request,
    body: UserCreate,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_superadmin()),
):
    # Check uniqueness
    if db.query(AdminUser).filter(AdminUser.username == body.username).first():
        raise HTTPException(400, "Username already taken")
    if db.query(AdminUser).filter(AdminUser.email == body.email).first():
        raise HTTPException(400, "Email already registered")

    # Prevent creating a role higher than your own
    if body.role == Role.SUPERADMIN and current_user.role != Role.SUPERADMIN:
        raise HTTPException(403, "Only superadmins can create superadmin accounts")

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

    log_action(db, current_user, "CREATE_USER", "admin_users", str(user.id),
               {"username": user.username, "role": user.role}, request.client.host)

    return UserOut.model_validate(user)


# ── UPDATE USER (superadmin only) ──
@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    request: Request,
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_superadmin()),
):
    user = db.query(AdminUser).filter(AdminUser.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    # Can't downgrade or change the only superadmin
    if body.role and user.role == Role.SUPERADMIN and body.role != Role.SUPERADMIN:
        count = db.query(AdminUser).filter(AdminUser.role == Role.SUPERADMIN).count()
        if count <= 1:
            raise HTTPException(400, "Cannot demote the only superadmin")

    if body.email:
        user.email = body.email
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.role:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.password:
        user.password_hash = hash_password(body.password)

    db.commit()
    db.refresh(user)
    log_action(db, current_user, "UPDATE_USER", "admin_users", str(user_id),
               {"changes": body.model_dump(exclude_none=True)}, request.client.host)
    return UserOut.model_validate(user)


# ── DELETE USER (superadmin only, can't self-delete) ──
@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    request: Request,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_superadmin()),
):
    if current_user.id == user_id:
        raise HTTPException(400, "Cannot delete your own account")

    user = db.query(AdminUser).filter(AdminUser.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    if user.role == Role.SUPERADMIN:
        count = db.query(AdminUser).filter(AdminUser.role == Role.SUPERADMIN).count()
        if count <= 1:
            raise HTTPException(400, "Cannot delete the only superadmin")

    log_action(db, current_user, "DELETE_USER", "admin_users", str(user_id),
               {"username": user.username}, request.client.host)
    db.delete(user)
    db.commit()


# ── ACTIVITY LOG (admin+) ──
@router.get("/activity")
async def get_activity(
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
