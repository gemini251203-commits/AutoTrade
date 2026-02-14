"""
API Dependencies
=================
FastAPI dependency injection functions for authentication and database.

Usage:
    from app.api.deps import get_current_user, get_db, CurrentUser, DbSession
    
    @router.get("/protected")
    async def protected_route(user: CurrentUser):
        return {"user": user.username}
"""

from typing import Annotated, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt, JWTError

from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.core.config import settings


# ============================================
# OAuth2 Scheme
# ============================================

# tokenUrl must match the token endpoint path
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


# ============================================
# Database Session Dependency
# ============================================

async def get_db():
    """
    Get an async database session.
    
    Yields:
        AsyncSession: Database session
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# ============================================
# User Authentication Dependencies
# ============================================

async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """
    Get the current authenticated user from JWT token.
    
    Args:
        token: The JWT access token from Authorization header
        db: Database session
    
    Returns:
        User: The authenticated user object
    
    Raises:
        HTTPException 401: If token is invalid or user not found
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    # Decode token inline (avoid circular import)
    try:
        payload = jwt.decode(
            token, 
            settings.jwt_secret_key, 
            algorithms=[settings.jwt_algorithm]
        )
        username: Optional[str] = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    # Fetch user from database
    result = await db.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one_or_none()
    
    if user is None:
        raise credentials_exception
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is disabled",
        )
    
    return user


async def get_current_active_superuser(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """
    Get the current user and verify they are a superuser.
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough privileges",
        )
    return current_user


# Type aliases for cleaner dependency injection
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentSuperuser = Annotated[User, Depends(get_current_active_superuser)]
DbSession = Annotated[AsyncSession, Depends(get_db)]
