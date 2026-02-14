"""
Global Error Handler Middleware
================================
统一异常处理中间件

功能:
1. 捕获所有未处理异常，返回统一 JSON 格式
2. 自动生成 request_id 便于追踪
3. 记录错误日志
4. 区分开发/生产环境输出

响应格式:
    {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "...",
            "request_id": "uuid"
        }
    }
"""

import uuid
import traceback
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from loguru import logger


def setup_error_handlers(app):
    """
    注册全局异常处理器到 FastAPI 应用
    
    用法:
        from app.middleware.error_handler import setup_error_handlers
        setup_error_handlers(app)
    """
    
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """
        处理 HTTPException (401, 403, 404, 429 等)
        
        保持原有行为，但统一格式
        """
        request_id = _get_request_id(request)
        
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": _status_to_code(exc.status_code),
                    "message": exc.detail,
                    "request_id": request_id,
                }
            },
            headers=getattr(exc, "headers", None),
        )
    
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """
        处理请求参数验证错误
        
        返回字段级错误信息，方便前端展示
        """
        request_id = _get_request_id(request)
        
        # 提取字段级错误
        errors = []
        for error in exc.errors():
            field = " → ".join(str(loc) for loc in error.get("loc", []))
            errors.append({
                "field": field,
                "message": error.get("msg", "Invalid value"),
                "type": error.get("type", "value_error"),
            })
        
        logger.warning(
            f"[ErrorHandler] Validation error on {request.method} {request.url.path} "
            f"| request_id={request_id} | errors={errors}"
        )
        
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "request_id": request_id,
                    "details": errors,
                }
            },
        )
    
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        """
        处理所有未捕获的异常
        
        - 记录完整堆栈到日志
        - 返回安全的错误信息 (不泄露内部细节)
        """
        request_id = _get_request_id(request)
        
        # 记录完整错误日志
        logger.error(
            f"[ErrorHandler] Unhandled exception on {request.method} {request.url.path} "
            f"| request_id={request_id}\n"
            f"{traceback.format_exc()}"
        )
        
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An internal error occurred. Please try again later.",
                    "request_id": request_id,
                }
            },
        )
    
    logger.info("[ErrorHandler] Global error handlers registered")


# ==================== Helper Functions ====================

def _get_request_id(request: Request) -> str:
    """获取或生成请求 ID"""
    return request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])


def _status_to_code(status_code: int) -> str:
    """HTTP 状态码映射到错误代码"""
    mapping = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
        500: "INTERNAL_ERROR",
        502: "BAD_GATEWAY",
        503: "SERVICE_UNAVAILABLE",
    }
    return mapping.get(status_code, f"HTTP_{status_code}")
