"""
Encryption Utilities
====================
API Key 加密/解密工具

使用 Fernet 对称加密，保证 API Key 安全存储
"""

import os
import base64
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from loguru import logger

from app.core.config import settings


def get_encryption_key() -> bytes:
    """
    获取加密密钥
    
    优先从环境变量读取，如果不存在则使用 JWT_SECRET_KEY 派生
    """
    # 尝试从环境变量获取专用加密密钥 (Fernet key = 32 bytes, base64url encoded)
    encryption_key = os.getenv("ENCRYPTION_KEY")
    
    if encryption_key:
        try:
            # Fernet key 本身就是 base64 encoded，直接 encode 为 bytes 即可
            key_bytes = encryption_key.encode()
            # 验证是否是有效的 Fernet key
            Fernet(key_bytes)
            return key_bytes
        except Exception:
            logger.warning("[Encryption] ENCRYPTION_KEY env var invalid, falling back to JWT_SECRET_KEY")
    
    # 从 JWT_SECRET_KEY 派生 (使用前32字节)
    secret = settings.jwt_secret_key
    padded = (secret * 3)[:32]
    return base64.urlsafe_b64encode(padded.encode())


def encrypt_api_key(plain_key: str) -> str:
    """
    加密 API Key
    
    Args:
        plain_key: 明文 API Key
        
    Returns:
        加密后的字符串
    """
    if not plain_key:
        return ""
    
    try:
        fernet = Fernet(get_encryption_key())
        encrypted = fernet.encrypt(plain_key.encode())
        return encrypted.decode()
    except Exception as e:
        logger.error(f"[Encryption] Failed to encrypt API key: {e}")
        raise ValueError("Encryption failed")


def decrypt_api_key(encrypted_key: str) -> str:
    """
    解密 API Key
    
    Args:
        encrypted_key: 加密后的 API Key
        
    Returns:
        明文 API Key
    """
    if not encrypted_key:
        return ""
    
    try:
        fernet = Fernet(get_encryption_key())
        decrypted = fernet.decrypt(encrypted_key.encode())
        return decrypted.decode()
    except InvalidToken:
        logger.error("[Encryption] Invalid token - key may have been tampered or wrong encryption key")
        raise ValueError("Decryption failed - invalid key")
    except Exception as e:
        logger.error(f"[Encryption] Failed to decrypt API key: {e}")
        raise ValueError("Decryption failed")



def decrypt_api_key_safe(encrypted_key: str) -> str:
    """
    安全解密 API Key — 自动兼容多种加密格式
    
    按优先级依次尝试:
    1. Fernet 解密
    2. Base64 解码
    3. 原始值直接返回 (sk-xxx 格式)
    
    Args:
        encrypted_key: 加密后的 API Key
        
    Returns:
        明文 API Key
        
    Raises:
        ValueError: 所有解密方式均失败
    """
    if not encrypted_key:
        return ""
    
    # 方法 1: Fernet
    try:
        return decrypt_api_key(encrypted_key)
    except Exception:
        pass
    
    # 方法 2: Base64 (历史兼容)
    try:
        decoded = base64.b64decode(encrypted_key.encode()).decode()
        if decoded and decoded.isprintable() and len(decoded) > 5:
            return decoded
    except Exception:
        pass
    
    # 方法 3: 原始值 (未加密的 key)
    if encrypted_key.startswith("sk-") or len(encrypted_key) > 20:
        return encrypted_key
    
    raise ValueError("Decryption failed - unknown format")


# 别名 (向后兼容)
encrypt_value = encrypt_api_key


def mask_api_key(api_key: str, show_chars: int = 4) -> str:
    """
    脱敏显示 API Key
    
    Args:
        api_key: 原始 API Key
        show_chars: 显示末尾几位
        
    Returns:
        脱敏后的字符串，如 "sk-****1234"
    """
    if not api_key:
        return ""
    
    if len(api_key) <= show_chars:
        return "*" * len(api_key)
    
    prefix = api_key[:3] if api_key.startswith("sk-") else ""
    suffix = api_key[-show_chars:]
    masked_len = len(api_key) - len(prefix) - show_chars
    
    return f"{prefix}{'*' * min(masked_len, 8)}{suffix}"
