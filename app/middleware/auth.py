# app/middleware/auth.py
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from app.models.database import get_db, AdminUser, Role

JWT_SECRET = os.getenv("JWT_SECRET", "change-this-secret")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ── PASSWORD UTILS ──
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── TOKEN UTILS ──
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=JWT_EXPIRE_MINUTES))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


# ── GET CURRENT USER ──
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> AdminUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        user_id: int = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(AdminUser).filter(AdminUser.id == int(user_id), AdminUser.is_active == True).first()
    if user is None:
        raise credentials_exception
    return user


# ── ROLE DEPENDENCY FACTORIES ──

def require_roles(*roles: str):
    """Dependency that requires the user to have one of the given roles."""
    async def _check(current_user: AdminUser = Depends(get_current_user)) -> AdminUser:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role(s): {', '.join(roles)}. Your role: {current_user.role}",
            )
        return current_user
    return _check


def require_write():
    """Requires admin or superadmin (not viewer)."""
    return require_roles(Role.ADMIN, Role.SUPERADMIN)


def require_superadmin():
    """Requires superadmin only."""
    return require_roles(Role.SUPERADMIN)


def require_any():
    """Requires any authenticated admin (including viewer)."""
    return require_roles(Role.VIEWER, Role.ADMIN, Role.SUPERADMIN)


# ── CONVENIENCE DEPS ──
CurrentUser = Depends(get_current_user)
WriteUser = Depends(require_write())
SuperAdmin = Depends(require_superadmin())
AnyUser = Depends(require_any())
