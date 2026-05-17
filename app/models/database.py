# app/models/database.py
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Boolean,
    DateTime, ForeignKey, func, text
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship
from sqlalchemy.pool import StaticPool
from datetime import datetime, timezone
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./strapeezzy.db")

# SQLite needs special connect args
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)


class Base(DeclarativeBase):
    pass


def utcnow():
    return datetime.now(timezone.utc)


# ── USER ROLES ──
class Role:
    SUPERADMIN = "superadmin"   # Full access, can manage users, delete orders
    ADMIN = "admin"             # Orders, fulfillment, waitlist, campaigns, design
    VIEWER = "viewer"           # Read-only access to orders and waitlist


# ── MODELS ──

class AdminUser(Base):
    __tablename__ = "admin_users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(256), unique=True, nullable=False, index=True)
    full_name = Column(String(128), nullable=True)
    password_hash = Column(String(256), nullable=False)
    role = Column(String(32), nullable=False, default=Role.ADMIN)
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Permissions helper
    @property
    def can_delete(self):
        return self.role == Role.SUPERADMIN

    @property
    def can_write(self):
        return self.role in (Role.SUPERADMIN, Role.ADMIN)

    @property
    def is_superadmin(self):
        return self.role == Role.SUPERADMIN


class WaitlistEntry(Base):
    __tablename__ = "waitlist"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(256), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=True)
    phone = Column(String(32), nullable=True)
    notify_sms = Column(Boolean, default=False)
    source = Column(String(64), default="website")
    notified = Column(Boolean, default=False)
    notified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String(32), unique=True, nullable=False, index=True)
    stripe_payment_intent = Column(String(128), unique=True, nullable=True, index=True)
    customer_name = Column(String(128), nullable=False)
    customer_email = Column(String(256), nullable=False, index=True)
    customer_phone = Column(String(32), nullable=True)
    shipping_address = Column(Text, nullable=True)
    product_name = Column(String(128), nullable=False)
    product_variant = Column(String(128), nullable=True)
    quantity = Column(Integer, default=1)
    unit_price = Column(Integer, nullable=False)   # cents
    total_amount = Column(Integer, nullable=False)  # cents
    currency = Column(String(8), default="usd")
    status = Column(String(32), default="pending")
    fulfillment_status = Column(String(32), default="unfulfilled")
    tracking_number = Column(String(128), nullable=True)
    tracking_carrier = Column(String(64), nullable=True)
    tracking_url = Column(String(512), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    shipped_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)


class SiteConfig(Base):
    __tablename__ = "site_config"
    key = Column(String(128), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ActivityLog(Base):
    __tablename__ = "activity_log"
    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("admin_users.id"), nullable=True)
    admin_username = Column(String(64), nullable=True)
    action = Column(String(128), nullable=False)
    entity = Column(String(64), nullable=True)
    entity_id = Column(String(64), nullable=True)
    details = Column(Text, nullable=True)
    ip_address = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class EmailCampaign(Base):
    __tablename__ = "email_campaigns"
    id = Column(Integer, primary_key=True, index=True)
    subject = Column(String(256), nullable=False)
    body = Column(Text, nullable=False)
    sent_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    status = Column(String(32), default="draft")
    sent_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(Integer, ForeignKey("admin_users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    price_cents = Column(Integer, nullable=False)
    image_url = Column(String(512), nullable=True)
    image_url_2 = Column(String(512), nullable=True)
    colorway = Column(String(128), nullable=True)
    stock_quantity = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ── DB SESSION ──
from sqlalchemy.orm import sessionmaker
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── CREATE TABLES ──
def init_db():
    Base.metadata.create_all(bind=engine)
    # Runtime migration: add image_url_2 if missing
    try:
        with engine.connect() as conn:
            if DATABASE_URL.startswith("sqlite"):
                result = conn.execute(text("PRAGMA table_info(products)"))
                cols = [row[1] for row in result]
                if "image_url_2" not in cols:
                    conn.execute(text("ALTER TABLE products ADD COLUMN image_url_2 VARCHAR(512)"))
                    conn.commit()
            else:
                conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_url_2 VARCHAR(512)"))
                conn.commit()
    except Exception:
        pass
