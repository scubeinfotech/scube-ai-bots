"""
Authentication service for admin users
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
import os

import jwt
from passlib.context import CryptContext
from pydantic import BaseModel

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT settings
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 hours


class TokenData(BaseModel):
    admin_id: str
    username: str
    exp: Optional[datetime] = None


def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password"""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(admin_id: str = None, username: str = None, expires_delta: Optional[timedelta] = None, data: Optional[dict] = None) -> str:
    """Create JWT access token.

    Supports both the legacy admin signature (admin_id, username) and a
    flexible ``data`` dict for tenant users and other payload shapes.
    """
    if expires_delta is None:
        expires_delta = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    expire = datetime.now(timezone.utc) + expires_delta

    if data is not None:
        to_encode = dict(data)
        to_encode["exp"] = expire
    else:
        to_encode = {
            "admin_id": admin_id,
            "username": username,
            "exp": expire,
        }

    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> Optional[TokenData]:
    """Decode and validate JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        admin_id = payload.get("admin_id")
        username = payload.get("username")
        if admin_id is None or username is None:
            return None
        return TokenData(admin_id=admin_id, username=username)
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
