"""
Billing models - invoices and subscription tracking
"""
from sqlalchemy import Column, String, DateTime, Boolean, Float, ForeignKey, Text, Integer
from sqlalchemy.sql import func
from app.database import Base
import uuid


class Invoice(Base):
    """Invoice for tenant subscription payments (Stripe or PayNow)"""
    __tablename__ = "invoices"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)

    amount = Column(Float, nullable=False)
    currency = Column(String(3), default="SGD")
    description = Column(String(500), nullable=True)
    plan = Column(String(50), nullable=True)

    payment_method = Column(String(20), nullable=True)
    payment_status = Column(String(20), default="pending")
    stripe_payment_intent_id = Column(String(255), nullable=True)
    stripe_checkout_session_id = Column(String(255), nullable=True)
    paynow_qr_data = Column(Text, nullable=True)
    paynow_reference = Column(String(100), nullable=True)

    due_date = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<Invoice(id={self.id}, tenant_id={self.tenant_id}, amount={self.amount}, status={self.payment_status})>"


class SubscriptionPlan(Base):
    """Subscription plan definitions — configurable from Admin Panel"""
    __tablename__ = "subscription_plans"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(50), unique=True, nullable=False)
    display_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    price_monthly = Column(Float, nullable=False)
    price_annual = Column(Float, nullable=True)
    currency = Column(String(3), default="SGD")
    trial_days = Column(Integer, default=7)

    features = Column(Text, nullable=True)
    includes_chatbot = Column(Boolean, default=True)
    includes_whatsapp = Column(Boolean, default=False)
    monthly_message_limit = Column(Integer, default=1000)
    max_documents = Column(Integer, default=50)
    priority_support = Column(Boolean, default=False)

    stripe_price_id_monthly = Column(String(255), nullable=True)
    stripe_price_id_annual = Column(String(255), nullable=True)

    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<SubscriptionPlan(id={self.id}, name={self.name}, price={self.price_monthly})>"
