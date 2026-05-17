# app/routes/products.py
import json
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
import os
import shutil

from app.models.database import get_db, Product, ActivityLog, AdminUser, Role
from app.middleware.auth import get_current_user, require_roles

router = APIRouter(prefix="/api/products", tags=["products"])

UPLOAD_DIR = "public/images"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ── LIST PRODUCTS ──
@router.get("/")
async def list_products(db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.is_active == True).all()
    return [
        {
            "id": p.id,
            "sku": p.sku,
            "name": p.name,
            "description": p.description,
            "price_cents": p.price_cents,
            "image_url": p.image_url,
            "image_url_2": p.image_url_2,
            "colorway": p.colorway,
            "stock_quantity": p.stock_quantity,
        }
        for p in products
    ]


# ── GET SINGLE PRODUCT ──
@router.get("/{product_id}")
async def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return {
        "id": product.id,
        "sku": product.sku,
        "name": product.name,
        "description": product.description,
        "price_cents": product.price_cents,
        "image_url": product.image_url,
        "image_url_2": product.image_url_2,
        "colorway": product.colorway,
        "stock_quantity": product.stock_quantity,
        "is_active": product.is_active,
    }


# ── ADMIN: LIST ALL PRODUCTS (including inactive) ──
@router.get("/admin/all", tags=["admin"])
async def admin_list_products(
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    products = db.query(Product).order_by(Product.created_at.desc()).all()
    return [
        {
            "id": p.id,
            "sku": p.sku,
            "name": p.name,
            "description": p.description,
            "price_cents": p.price_cents,
            "image_url": p.image_url,
            "image_url_2": p.image_url_2,
            "colorway": p.colorway,
            "stock_quantity": p.stock_quantity,
            "is_active": p.is_active,
            "created_at": p.created_at.isoformat(),
            "updated_at": p.updated_at.isoformat(),
        }
        for p in products
    ]


# ── ADMIN: CREATE PRODUCT ──
@router.post("/admin", tags=["admin"])
async def create_product(
    sku: str = Form(...),
    name: str = Form(...),
    description: Optional[str] = Form(None),
    price_cents: int = Form(...),
    colorway: Optional[str] = Form(None),
    stock_quantity: int = Form(0),
    image_url: Optional[str] = Form(None),
    image_url_2: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    file2: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    # Check if SKU already exists
    if db.query(Product).filter(Product.sku == sku).first():
        raise HTTPException(status_code=400, detail="SKU already exists")

    if file:
        filename = f"{sku.lower()}-{os.path.basename(file.filename.replace('\\', '/'))}"
        filepath = os.path.join(UPLOAD_DIR, filename)
        try:
            with open(filepath, "wb") as f:
                content = await file.read()
                f.write(content)
            image_url = f"/images/{filename}"
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save image: {str(e)}")

    if file2:
        filename2 = f"{sku.lower()}-2-{os.path.basename(file2.filename.replace('\\', '/'))}"
        filepath2 = os.path.join(UPLOAD_DIR, filename2)
        try:
            with open(filepath2, "wb") as f:
                content = await file2.read()
                f.write(content)
            image_url_2 = f"/images/{filename2}"
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save second image: {str(e)}")

    product = Product(
        sku=sku,
        name=name,
        description=description,
        price_cents=price_cents,
        image_url=image_url,
        image_url_2=image_url_2,
        colorway=colorway,
        stock_quantity=stock_quantity,
    )
    db.add(product)
    db.commit()
    db.refresh(product)

    log = ActivityLog(
        admin_id=current_user.id,
        admin_username=current_user.username,
        action="CREATE_PRODUCT",
        entity="products",
        entity_id=str(product.id),
        details=json.dumps({"sku": sku, "name": name}),
    )
    db.add(log)
    db.commit()

    return {"success": True, "product_id": product.id}


# ── ADMIN: UPDATE PRODUCT ──
@router.patch("/admin/{product_id}", tags=["admin"])
async def update_product(
    product_id: int,
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    price_cents: Optional[int] = Form(None),
    colorway: Optional[str] = Form(None),
    stock_quantity: Optional[int] = Form(None),
    is_active: Optional[bool] = Form(None),
    image_url: Optional[str] = Form(None),
    image_url_2: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    file2: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    updates = {}
    if name is not None:
        product.name = name
        updates["name"] = name
    if description is not None:
        product.description = description
        updates["description"] = description
    if price_cents is not None:
        product.price_cents = price_cents
        updates["price_cents"] = price_cents
    if colorway is not None:
        product.colorway = colorway
        updates["colorway"] = colorway
    if stock_quantity is not None:
        product.stock_quantity = stock_quantity
        updates["stock_quantity"] = stock_quantity
    if is_active is not None:
        product.is_active = is_active
        updates["is_active"] = is_active
    if image_url is not None and not file:
        product.image_url = image_url
        updates["image_url"] = image_url
    if image_url_2 is not None and not file2:
        product.image_url_2 = image_url_2
        updates["image_url_2"] = image_url_2

    if file:
        filename = f"{product.sku.lower()}-{os.path.basename(file.filename.replace('\\', '/'))}"
        filepath = os.path.join(UPLOAD_DIR, filename)
        try:
            with open(filepath, "wb") as f:
                content = await file.read()
                f.write(content)
            product.image_url = f"/images/{filename}"
            updates["image_url"] = product.image_url
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save image: {str(e)}")

    if file2:
        filename2 = f"{product.sku.lower()}-2-{os.path.basename(file2.filename.replace('\\', '/'))}"
        filepath2 = os.path.join(UPLOAD_DIR, filename2)
        try:
            with open(filepath2, "wb") as f:
                content = await file2.read()
                f.write(content)
            product.image_url_2 = f"/images/{filename2}"
            updates["image_url_2"] = product.image_url_2
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save second image: {str(e)}")

    product.updated_at = datetime.now(timezone.utc)
    db.commit()

    log = ActivityLog(
        admin_id=current_user.id,
        admin_username=current_user.username,
        action="UPDATE_PRODUCT",
        entity="products",
        entity_id=str(product.id),
        details=json.dumps(updates),
    )
    db.add(log)
    db.commit()

    return {"success": True, "updated": updates}


# ── ADMIN: DELETE PRODUCT ──
@router.delete("/admin/{product_id}", tags=["admin"])
async def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.SUPERADMIN)),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Delete image if exists
    if product.image_url:
        try:
            filepath = product.image_url.lstrip("/")
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass

    db.delete(product)
    db.commit()

    log = ActivityLog(
        admin_id=current_user.id,
        admin_username=current_user.username,
        action="DELETE_PRODUCT",
        entity="products",
        entity_id=str(product.id),
        details=json.dumps({"sku": product.sku}),
    )
    db.add(log)
    db.commit()

    return {"success": True}
