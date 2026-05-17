# app/models/schemas.py
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, List
from datetime import datetime


# ── AUTH / USERS ──

class UserCreate(BaseModel):
    username: str
    email: EmailStr
    full_name: Optional[str] = None
    password: str
    role: str = "admin"

    @field_validator("role")
    @classmethod
    def validate_role(cls, v):
        if v not in ("superadmin", "admin", "viewer"):
            raise ValueError("Role must be superadmin, admin, or viewer")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    full_name: Optional[str]
    role: str
    is_active: bool
    last_login: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ── WAITLIST ──

class WaitlistJoin(BaseModel):
    email: EmailStr
    name: Optional[str] = None
    phone: Optional[str] = None
    notify_sms: bool = False
    source: str = "website"


class WaitlistOut(BaseModel):
    id: int
    email: str
    name: Optional[str]
    phone: Optional[str]
    notify_sms: bool
    notified: bool
    notified_at: Optional[datetime]
    source: str
    created_at: datetime

    model_config = {"from_attributes": True}


class WaitlistCountsUpdate(BaseModel):
    waitlist_count: Optional[int] = None
    maillist_count: Optional[int] = None


class CountsOut(BaseModel):
    waitlist_count: int
    maillist_count: int
    launch_date: Optional[str]
    waitlist_active: bool


# ── ORDERS ──

class OrderCreate(BaseModel):
    customer_name: str
    customer_email: EmailStr
    customer_phone: Optional[str] = None
    product_name: str
    product_variant: Optional[str] = None
    quantity: int = 1
    unit_price: int  # cents
    shipping_address: Optional[str] = None
    notes: Optional[str] = None


class FulfillmentUpdate(BaseModel):
    fulfillment_status: Optional[str] = None
    tracking_number: Optional[str] = None
    tracking_carrier: Optional[str] = None
    tracking_url: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("fulfillment_status")
    @classmethod
    def validate_status(cls, v):
        if v and v not in ("unfulfilled", "in_progress", "shipped", "delivered"):
            raise ValueError("Invalid fulfillment status")
        return v


class OrderStatusUpdate(BaseModel):
    status: str
    notes: Optional[str] = None


class OrderOut(BaseModel):
    id: int
    order_number: str
    stripe_payment_intent: Optional[str]
    customer_name: str
    customer_email: str
    customer_phone: Optional[str]
    shipping_address: Optional[str]
    product_name: str
    product_variant: Optional[str]
    quantity: int
    unit_price: int
    total_amount: int
    currency: str
    status: str
    fulfillment_status: str
    tracking_number: Optional[str]
    tracking_carrier: Optional[str]
    tracking_url: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    shipped_at: Optional[datetime]
    delivered_at: Optional[datetime]

    model_config = {"from_attributes": True}


class OrderStats(BaseModel):
    total_orders: int
    total_revenue: int
    unfulfilled: int
    shipped: int
    delivered: int
    today: int
    this_week: int
    by_product: List[dict]


# ── STRIPE ──

class PaymentIntentCreate(BaseModel):
    product_name: str
    customer_email: Optional[EmailStr] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    shipping_address: Optional[str] = None


class PaymentIntentOut(BaseModel):
    client_secret: str
    amount: int


# ── CONFIG ──

class ConfigUpdate(BaseModel):
    site_title: Optional[str] = None
    hero_headline_line1: Optional[str] = None
    hero_headline_line2: Optional[str] = None
    hero_headline_line3: Optional[str] = None
    hero_subtitle: Optional[str] = None
    strap_price: Optional[str] = None
    shipping_threshold: Optional[str] = None
    announcement_bar: Optional[str] = None
    announcement_active: Optional[str] = None
    waitlist_active: Optional[str] = None
    store_active: Optional[str] = None
    sms_notifications: Optional[str] = None
    launch_date: Optional[str] = None
    waitlist_count: Optional[str] = None
    maillist_count: Optional[str] = None
    hero_slide_interval: Optional[str] = None
    logo_type: Optional[str] = None
    logo_text: Optional[str] = None
    logo_image_url: Optional[str] = None
    hero_badge: Optional[str] = None
    hero_cta1_text: Optional[str] = None
    hero_cta2_text: Optional[str] = None
    nav_btn_text: Optional[str] = None
    nav_link1_text: Optional[str] = None
    nav_link2_text: Optional[str] = None
    products_title: Optional[str] = None
    waitlist_title: Optional[str] = None
    waitlist_description: Optional[str] = None
    waitlist_btn_text: Optional[str] = None


# ── PAYMENT ──


# ── CAMPAIGNS ──

class CampaignCreate(BaseModel):
    subject: str
    body: str


class CampaignOut(BaseModel):
    id: int
    subject: str
    sent_count: int
    failed_count: int
    status: str
    sent_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── NOTIFY ──

class NotifyAllRequest(BaseModel):
    shop_url: str = "https://strapeezzy.com"
    message: Optional[str] = None
