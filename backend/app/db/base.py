"""
Database Base
==============
SQLAlchemy 声明式基类
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    所有模型的基类
    
    使用 SQLAlchemy 2.0 声明式基类
    """
    pass
