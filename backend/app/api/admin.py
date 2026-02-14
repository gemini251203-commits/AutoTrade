"""
Admin API
==========
管理员专用 API 端点

Endpoints:
    GET /api/admin/users - 获取所有用户列表 (仅管理员)
"""

from typing import List
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from loguru import logger

from app.api.deps import DbSession, CurrentUser
from app.models.user import User


router = APIRouter(tags=["Admin"])


# ============================================
# Schemas
# ============================================

class UserListItem(BaseModel):
    """用户列表项"""
    id: int
    username: str
    email: str
    is_active: bool
    is_superuser: bool

    class Config:
        from_attributes = True


# ============================================
# Endpoints
# ============================================

@router.get("/users", response_model=List[UserListItem])
async def list_all_users(
    current_user: CurrentUser,
    db: DbSession,
):
    """
    获取所有用户列表
    
    仅管理员可调用
    
    Returns:
        用户列表
    """
    # 权限检查
    if not current_user.is_superuser:
        logger.warning(f"[Admin] Non-admin user {current_user.username} tried to access user list")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    
    # 查询所有用户
    result = await db.execute(select(User).order_by(User.id))
    users = result.scalars().all()
    
    logger.info(f"[Admin] User {current_user.username} fetched {len(users)} users")
    
    return users


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    删除用户
    
    仅管理员可调用
    不能删除自己
    """
    # 权限检查
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    
    # 不能删除自己
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete yourself",
        )
    
    # 查找用户
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # 删除用户
    await db.delete(user)
    await db.commit()
    
    logger.info(f"[Admin] User {current_user.username} deleted user {user.username}")
    
    return {"message": f"User {user.username} deleted"}
