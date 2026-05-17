# app/routes/media.py
import os
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.models.database import get_db, HeroImage, GalleryImage, AdminUser, Role
from app.middleware.auth import require_roles

router = APIRouter(prefix="/api/media", tags=["media"])

UPLOAD_DIR = "public/images"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _save_upload(file: UploadFile, prefix: str) -> str:
    safe = os.path.basename(file.filename.replace("\\", "/")).replace(" ", "-")
    filename = f"{prefix}-{int(datetime.now(timezone.utc).timestamp())}-{safe}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    content = file.file.read()
    with open(filepath, "wb") as f:
        f.write(content)
    return f"/images/{filename}"


# ── PUBLIC: list active hero images ──
@router.get("/hero")
async def list_hero_images(db: Session = Depends(get_db)):
    images = (
        db.query(HeroImage)
        .filter(HeroImage.is_active == True)
        .order_by(HeroImage.position, HeroImage.id)
        .all()
    )
    return [{"id": i.id, "url": i.url, "alt_text": i.alt_text, "position": i.position} for i in images]


# ── ADMIN: upload hero image ──
@router.post("/hero")
async def upload_hero_image(
    file: UploadFile = File(...),
    alt_text: Optional[str] = Form(""),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    if not file.content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image")
    url = _save_upload(file, "hero")
    max_pos = db.query(HeroImage).count()
    img = HeroImage(url=url, alt_text=alt_text or "", position=max_pos)
    db.add(img)
    db.commit()
    db.refresh(img)
    return {"id": img.id, "url": img.url, "alt_text": img.alt_text, "position": img.position, "is_active": img.is_active}


# ── ADMIN: add hero image by URL (from gallery) ──
@router.post("/hero/from-url")
async def add_hero_image_from_url(
    url: str = Form(...),
    alt_text: Optional[str] = Form(""),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    max_pos = db.query(HeroImage).count()
    img = HeroImage(url=url, alt_text=alt_text or "", position=max_pos)
    db.add(img)
    db.commit()
    db.refresh(img)
    return {"id": img.id, "url": img.url, "alt_text": img.alt_text, "position": img.position, "is_active": img.is_active}


# ── ADMIN: list all hero images (including inactive) ──
@router.get("/hero/all")
async def list_all_hero_images(
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    images = db.query(HeroImage).order_by(HeroImage.position, HeroImage.id).all()
    return [
        {"id": i.id, "url": i.url, "alt_text": i.alt_text, "position": i.position, "is_active": i.is_active}
        for i in images
    ]


# ── ADMIN: update hero image (position / active / alt) ──
@router.patch("/hero/{image_id}")
async def update_hero_image(
    image_id: int,
    position: Optional[int] = Form(None),
    is_active: Optional[bool] = Form(None),
    alt_text: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    img = db.query(HeroImage).filter(HeroImage.id == image_id).first()
    if not img:
        raise HTTPException(404, "Image not found")
    if position is not None:
        img.position = position
    if is_active is not None:
        img.is_active = is_active
    if alt_text is not None:
        img.alt_text = alt_text
    db.commit()
    return {"success": True}


# ── ADMIN: delete hero image ──
@router.delete("/hero/{image_id}")
async def delete_hero_image(
    image_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    img = db.query(HeroImage).filter(HeroImage.id == image_id).first()
    if not img:
        raise HTTPException(404, "Image not found")
    # Only delete the file if it's in our upload dir (not an external URL)
    if img.url.startswith("/images/"):
        filepath = img.url.lstrip("/")
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass
    db.delete(img)
    db.commit()
    return {"success": True}


# ── ADMIN: reorder hero images ──
@router.post("/hero/reorder")
async def reorder_hero_images(
    ids: str = Form(...),  # comma-separated ordered IDs
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    ordered = [int(x) for x in ids.split(",") if x.strip()]
    for pos, img_id in enumerate(ordered):
        db.query(HeroImage).filter(HeroImage.id == img_id).update({"position": pos})
    db.commit()
    return {"success": True}


# ── GALLERY: upload ──
@router.post("/gallery")
async def upload_gallery_image(
    file: UploadFile = File(...),
    alt_text: Optional[str] = Form(""),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    if not file.content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image")
    url = _save_upload(file, "gallery")
    img = GalleryImage(filename=os.path.basename(url), url=url, alt_text=alt_text or "")
    db.add(img)
    db.commit()
    db.refresh(img)
    return {"id": img.id, "url": img.url, "alt_text": img.alt_text, "filename": img.filename,
            "created_at": img.created_at.isoformat()}


# ── GALLERY: list ──
@router.get("/gallery")
async def list_gallery_images(
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    images = db.query(GalleryImage).order_by(GalleryImage.created_at.desc()).all()
    return [
        {"id": i.id, "url": i.url, "alt_text": i.alt_text, "filename": i.filename,
         "created_at": i.created_at.isoformat()}
        for i in images
    ]


# ── GALLERY: delete ──
@router.delete("/gallery/{image_id}")
async def delete_gallery_image(
    image_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    img = db.query(GalleryImage).filter(GalleryImage.id == image_id).first()
    if not img:
        raise HTTPException(404, "Image not found")
    if img.url.startswith("/images/"):
        filepath = img.url.lstrip("/")
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass
    db.delete(img)
    db.commit()
    return {"success": True}
