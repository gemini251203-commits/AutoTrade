"""
Middleware Package
==================
全局中间件模块
"""

from .error_handler import setup_error_handlers

__all__ = ["setup_error_handlers"]
