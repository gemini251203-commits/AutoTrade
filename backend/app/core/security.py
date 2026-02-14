"""
Security Utilities
===================
Password hashing and JWT token management.

Dependencies:
    pip install passlib argon2-cffi python-jose[cryptography]

Note:
    Using Argon2 instead of bcrypt for better Python 3.13 compatibility.
"""

from datetime import datetime, timedelta
from typing import Any, Optional

from jose import jwt, JWTError
from passlib.context import CryptContext
from pydantic import BaseModel

from app.core.config import settings


# ============================================
# Pydantic Schemas
# ============================================

class Token(BaseModel):
    """OAuth2 Token Response"""
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Decoded JWT Token Data"""
    username: Optional[str] = None


# ============================================
# Configuration
# ============================================

SECRET_KEY = settings.jwt_secret_key
ALGORITHM = settings.jwt_algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes

# Password hashing context (Argon2 - Python 3.13 compatible)
# ✅ argon2 replaces bcrypt for better compatibility
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


# ============================================
# Password Utilities
# ============================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password using Argon2."""
    return pwd_context.hash(password)


# ============================================
# JWT Token Utilities
# ============================================

def create_access_token(
    data: dict[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
    })
    
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    """Decode and validate a JWT access token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None
