# app/routes/products.py
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session
import httpx
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
            "gallery_images": json.loads(p.gallery_images or "[]"),
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
        "gallery_images": json.loads(product.gallery_images or "[]"),
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
            "gallery_images": json.loads(p.gallery_images or "[]"),
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
        _fname = os.path.basename(file.filename.replace('\\', '/'))
        filename = f"{sku.lower()}-{_fname}"
        filepath = os.path.join(UPLOAD_DIR, filename)
        try:
            with open(filepath, "wb") as f:
                content = await file.read()
                f.write(content)
            image_url = f"/images/{filename}"
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save image: {str(e)}")

    if file2:
        _fname2 = os.path.basename(file2.filename.replace('\\', '/'))
        filename2 = f"{sku.lower()}-2-{_fname2}"
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
        _fname = os.path.basename(file.filename.replace('\\', '/'))
        filename = f"{product.sku.lower()}-{_fname}"
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
        _fname2 = os.path.basename(file2.filename.replace('\\', '/'))
        filename2 = f"{product.sku.lower()}-2-{_fname2}"
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


# ── ADMIN: UPLOAD PRODUCT GALLERY IMAGE ──
@router.post("/admin/{product_id}/gallery", tags=["admin"])
async def upload_product_gallery(
    product_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    """Upload an image to product gallery"""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    _fname = os.path.basename(file.filename.replace('\\', '/'))
    filename = f"{product.sku.lower()}-gallery-{len(json.loads(product.gallery_images or '[]'))}-{_fname}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    try:
        with open(filepath, "wb") as f:
            content = await file.read()
            f.write(content)
        image_path = f"/images/{filename}"

        # Add to gallery_images JSON list
        gallery = json.loads(product.gallery_images or "[]")
        gallery.append(image_path)
        product.gallery_images = json.dumps(gallery)
        product.updated_at = datetime.now(timezone.utc)
        db.commit()

        return {"success": True, "image_url": image_path, "gallery_count": len(gallery)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save image: {str(e)}")


# ── ADMIN: GET PRODUCT GALLERY ──
@router.get("/admin/{product_id}/gallery", tags=["admin"])
async def get_product_gallery(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    """Get all gallery images for a product"""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    gallery = json.loads(product.gallery_images or "[]")
    return {"product_id": product_id, "gallery_images": gallery, "count": len(gallery)}


# ── ADMIN: DELETE GALLERY IMAGE ──
@router.delete("/admin/{product_id}/gallery/{image_index}", tags=["admin"])
async def delete_gallery_image(
    product_id: int,
    image_index: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    """Delete a gallery image from a product"""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    gallery = json.loads(product.gallery_images or "[]")
    if image_index < 0 or image_index >= len(gallery):
        raise HTTPException(status_code=400, detail="Invalid image index")

    image_url = gallery.pop(image_index)

    # Delete file if exists
    try:
        filepath = image_url.lstrip("/")
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        pass

    product.gallery_images = json.dumps(gallery)
    product.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {"success": True, "deleted": image_url}


# ── ADMIN: SCRAPE URL ──

class ScrapeUrlRequest(BaseModel):
    url: str


class _ProductHTMLParser(HTMLParser):
    """Minimal HTML parser that extracts meta tags, og tags, h1, title, and JSON-LD scripts."""

    def __init__(self):
        super().__init__()
        self.meta: dict[str, str] = {}          # name/property -> content
        self.json_ld_blocks: list[str] = []     # raw JSON-LD text
        self.h1: str = ""
        self.title: str = ""
        self._in_title = False
        self._in_h1 = False
        self._in_json_ld = False
        self._json_ld_buf = ""

    def handle_starttag(self, tag: str, attrs):
        attr = dict(attrs)
        if tag == "meta":
            key = attr.get("property") or attr.get("name") or ""
            content = attr.get("content", "")
            if key and content:
                self.meta[key.lower()] = content
        elif tag == "title":
            self._in_title = True
        elif tag == "h1":
            self._in_h1 = True
        elif tag == "script":
            if attr.get("type", "").lower() == "application/ld+json":
                self._in_json_ld = True
                self._json_ld_buf = ""

    def handle_endtag(self, tag: str):
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False
        elif tag == "script" and self._in_json_ld:
            self._in_json_ld = False
            self.json_ld_blocks.append(self._json_ld_buf)
            self._json_ld_buf = ""

    def handle_data(self, data: str):
        if self._in_title and not self.title:
            self.title = data.strip()
        if self._in_h1 and not self.h1:
            self.h1 = data.strip()
        if self._in_json_ld:
            self._json_ld_buf += data


def _parse_price_str(raw: str) -> int:
    """Strip currency symbols/whitespace, convert to pence (int)."""
    cleaned = re.sub(r"[^\d.]", "", raw.strip())
    if not cleaned:
        return 0
    try:
        return round(float(cleaned) * 100)
    except ValueError:
        return 0


def _extract_from_json_ld(blocks: list[str]) -> dict:
    """Find the first schema.org Product in the JSON-LD blocks."""
    result: dict = {}
    for raw in blocks:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue

        # Normalise: could be a single object or a @graph list
        candidates = []
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            if "@graph" in data:
                candidates = data["@graph"]
            else:
                candidates = [data]

        for item in candidates:
            if not isinstance(item, dict):
                continue
            item_type = item.get("@type", "")
            if isinstance(item_type, list):
                is_product = any(t.lower() == "product" for t in item_type)
            else:
                is_product = str(item_type).lower() == "product"
            if not is_product:
                continue

            # Name
            result["name"] = item.get("name", "")

            # Description
            result["description"] = item.get("description", "")

            # Image
            image = item.get("image", "")
            if isinstance(image, list):
                image = image[0] if image else ""
            if isinstance(image, dict):
                image = image.get("url", "")
            result["image_url"] = str(image) if image else ""

            # Price via offers
            offers = item.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price_raw = ""
            if isinstance(offers, dict):
                price_raw = str(offers.get("price", ""))
            if price_raw:
                result["price_cents"] = _parse_price_str(price_raw)

            # Color / colorway
            color = item.get("color", "") or item.get("colorway", "")
            result["colorway"] = str(color) if color else ""

            return result

    return result


@router.post("/admin/scrape-url", tags=["admin"])
async def scrape_product_url(
    body: ScrapeUrlRequest,
    current_user: AdminUser = Depends(require_roles(Role.ADMIN, Role.SUPERADMIN)),
):
    from urllib.parse import urlparse, urlunparse

    browser_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }
    json_headers = {
        "User-Agent": browser_headers["User-Agent"],
        "Accept": "application/json",
    }

    parsed = urlparse(body.url)

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:

        # ── Strategy 1: Shopify product JSON API ──
        # Shopify exposes /products/{handle}.json for any product page
        if "/products/" in parsed.path and not parsed.path.endswith(".json"):
            json_url = urlunparse(parsed._replace(
                path=parsed.path.rstrip("/") + ".json",
                query="",
            ))
            try:
                r = await client.get(json_url, headers=json_headers)
                if r.status_code == 200:
                    ct = r.headers.get("content-type", "")
                    if "json" in ct:
                        data = r.json()
                        p = data.get("product", data)
                        images = p.get("images", [])
                        img = images[0].get("src", "") if images else ""
                        variants = p.get("variants", [{}])
                        price_str = variants[0].get("price", "0") if variants else "0"
                        return {
                            "success": True,
                            "data": {
                                "name": p.get("title", ""),
                                "description": re.sub(r"<[^>]+>", " ", p.get("body_html", "") or "").strip(),
                                "price_cents": _parse_price_str(price_str),
                                "image_url": img,
                                "colorway": p.get("product_type", ""),
                                "source_url": body.url,
                            },
                        }
            except Exception:
                pass  # fall through to HTML scrape

        # ── Strategy 2: HTML scrape ──
        try:
            response = await client.get(body.url, headers=browser_headers)
            response.raise_for_status()
            html_text = response.text
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code == 403:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "The shop blocked the request (403). Most Shopify stores work — "
                        "make sure the URL contains '/products/'. Other platforms may "
                        "require pasting details manually."
                    ),
                )
            raise HTTPException(status_code=422, detail=f"Failed to fetch URL: HTTP {code}")
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Failed to fetch URL: {exc}")

    # ── 2. Parse HTML ──
    parser = _ProductHTMLParser()
    parser.feed(html_text)

    # ── 3. Build result: JSON-LD > OG > fallbacks ──
    ld = _extract_from_json_ld(parser.json_ld_blocks)
    meta = parser.meta

    name = ld.get("name") or meta.get("og:title") or parser.h1 or parser.title or ""
    description = (
        ld.get("description")
        or meta.get("og:description")
        or meta.get("description")
        or ""
    )
    image_url = ld.get("image_url") or meta.get("og:image") or ""
    colorway = ld.get("colorway", "")

    price_cents = ld.get("price_cents", 0)
    if not price_cents:
        raw_meta_price = meta.get("product:price:amount", "")
        if raw_meta_price:
            price_cents = _parse_price_str(raw_meta_price)

    return {
        "success": True,
        "data": {
            "name": name,
            "description": description,
            "price_cents": price_cents,
            "image_url": image_url,
            "colorway": colorway,
            "source_url": body.url,
        },
    }
