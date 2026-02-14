"""
Authentication API
===================
OAuth2 compatible token authentication endpoints.

Endpoints:
    POST /api/auth/token  - Login and get access token
    GET  /api/auth/me     - Get current user info

Dependencies:
    pip install passlib[bcrypt] python-jose[cryptography]
"""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)
from app.api.deps import get_db, get_current_user, DbSession, CurrentUser
from app.models.user import User


router = APIRouter(tags=["Authentication"])


# ============================================
# Schemas
# ============================================

class Token(BaseModel):
    """OAuth2 Token Response"""
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Decoded token data"""
    username: str | None = None


class UserResponse(BaseModel):
    """User information response"""
    id: int
    username: str
    email: str
    is_active: bool
    is_superuser: bool

    class Config:
        from_attributes = True


# ============================================
# Helper Functions
# ============================================

async def authenticate_user(
    db: AsyncSession,
    username: str,
    password: str
) -> User | None:
    """
    Authenticate a user by username and password.
    
    Args:
        db: Database session
        username: The username to authenticate
        password: The plain text password
    
    Returns:
        User if authentication successful, None otherwise
    """
    result = await db.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one_or_none()
    
    if user is None:
        return None
    
    if not verify_password(password, user.hashed_password):
        return None
    
    return user


async def init_default_admin(db: AsyncSession) -> None:
    """
    Initialize default admin user if no users exist.
    
    Creates admin/admin user for initial system access.
    Should be called on application startup.
    
    ⚠️ SECURITY: Change the default password after first login!
    """
    result = await db.execute(select(User).limit(1))
    existing_user = result.scalar_one_or_none()
    
    if existing_user is not None:
        logger.info("[Auth] Users table not empty, skipping admin creation")
        return
    
    # Create default admin user
    admin_user = User(
        username="admin",
        email="admin@autotrade.local",
        hashed_password=get_password_hash("admin"),
        is_active=True,
        is_superuser=True,
    )
    
    db.add(admin_user)
    await db.commit()
    
    logger.warning(
        "[Auth] Created default admin user (admin/admin). "
        "⚠️ CHANGE THIS PASSWORD IMMEDIATELY!"
    )


# ============================================
# Endpoints
# ============================================

@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
) -> Token:
    """
    OAuth2 compatible token login.
    
    Authenticate with username and password to receive a JWT access token.
    
    Args:
        form_data: OAuth2 password form (username, password)
        db: Database session
    
    Returns:
        Token: Access token response
    
    Raises:
        HTTPException 401: If credentials are invalid
    """
    user = await authenticate_user(db, form_data.username, form_data.password)
    
    if user is None:
        logger.warning(f"[Auth] Failed login attempt for: {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=access_token_expires,
    )
    
    logger.info(f"[Auth] User logged in: {user.username}")
    
    return Token(access_token=access_token, token_type="bearer")


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: CurrentUser,
) -> User:
    """
    Get current authenticated user information.
    
    Args:
        current_user: The authenticated user from JWT token
    
    Returns:
        UserResponse: Current user details
    """
    return current_user


class RegisterRequest(BaseModel):
    """User registration request"""
    username: str
    email: str
    password: str


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    req: RegisterRequest,
    db: DbSession,
) -> User:
    """
    Register a new user.
    
    Args:
        req: Registration request body (username, email, password)
        db: Database session
    
    Returns:
        UserResponse: Created user details
    
    Raises:
        HTTPException 400: If username or email already exists
    """
    # Check if username exists
    result = await db.execute(
        select(User).where(User.username == req.username)
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )
    
    # Check if email exists
    result = await db.execute(
        select(User).where(User.email == req.email)
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    
    # Create new user
    new_user = User(
        username=req.username,
        email=req.email,
        hashed_password=get_password_hash(req.password),
        is_active=True,
        is_superuser=False,
    )
    
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    
    logger.info(f"[Auth] New user registered: {req.username}")
    
    return new_user

