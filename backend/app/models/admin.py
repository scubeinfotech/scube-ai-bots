"""
Admin user models
"""
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean
from app.database import Base
import uuid


class AdminUser(Base):
    """Admin user for platform management"""
    __tablename__ = "admin_users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    password_reset_token = Column(String, nullable=True)
    password_reset_expires = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f"<AdminUser {self.username}>"


class Agreement(Base):
    """Service agreements for tenants"""
    __tablename__ = "agreements"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, nullable=False, index=True)
    agreement_name = Column(String, nullable=False)
    agreement_type = Column(String, nullable=False)  # 'service', 'sla', 'maintenance'
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    terms = Column(String, nullable=True)  # JSON stored as string
    status = Column(String, default='active')  # 'active', 'expired', 'pending'
    created_by = Column(String, nullable=False)  # admin_user id
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f"<Agreement {self.agreement_name} for {self.tenant_id}>"
