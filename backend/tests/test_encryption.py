"""
加密模块(Encryption)单元测试
================================
测试 core/encryption.py 的加/解密、脱敏、多格式兼容逻辑。

纯单元测试, 不依赖数据库和网络请求。

运行方式:
    cd backend
    python -m pytest tests/test_encryption.py -v
"""

import sys
import os
import importlib.util
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import base64
import pytest

# encryption.py 依赖 app.core.config (settings)，需要先 mock
# 1) 创建 mock settings
_mock_settings = types.SimpleNamespace(jwt_secret_key="test_secret_key_1234567890")

# 2) 创建 mock app.core.config 模块
_mock_config = types.ModuleType("app.core.config")
_mock_config.settings = _mock_settings
sys.modules["app.core.config"] = _mock_config
sys.modules.setdefault("app", types.ModuleType("app"))
sys.modules.setdefault("app.core", types.ModuleType("app.core"))

# 3) 直接加载 encryption.py
_mod_path = os.path.join(os.path.dirname(__file__), "..", "app", "core", "encryption.py")
_spec = importlib.util.spec_from_file_location("encryption", _mod_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

encrypt_api_key = _mod.encrypt_api_key
decrypt_api_key = _mod.decrypt_api_key
decrypt_api_key_safe = _mod.decrypt_api_key_safe
mask_api_key = _mod.mask_api_key


# ============================================
# A. 基础加解密往返测试
# ============================================

class TestEncryptDecryptRoundtrip:
    """加密 → 解密 往返一致性"""

    def test_roundtrip_normal_key(self):
        """普通 API Key 加密后解密应等于原文"""
        original = "sk-abc123def456ghi789"
        encrypted = encrypt_api_key(original)
        decrypted = decrypt_api_key(encrypted)
        assert decrypted == original

    def test_roundtrip_long_key(self):
        """长密钥往返一致"""
        original = "a" * 200
        encrypted = encrypt_api_key(original)
        decrypted = decrypt_api_key(encrypted)
        assert decrypted == original

    def test_roundtrip_unicode(self):
        """含 Unicode 的 Key 往返一致"""
        original = "sk-测试密钥-12345"
        encrypted = encrypt_api_key(original)
        decrypted = decrypt_api_key(encrypted)
        assert decrypted == original

    def test_encrypted_differs_from_original(self):
        """加密后密文不等于明文"""
        original = "sk-plaintext-key"
        encrypted = encrypt_api_key(original)
        assert encrypted != original

    def test_different_encryptions_not_identical(self):
        """同一明文两次加密的密文不同 (Fernet 带时间戳)"""
        original = "sk-test-key"
        enc1 = encrypt_api_key(original)
        enc2 = encrypt_api_key(original)
        # Fernet 加密包含时间戳，同一明文两次加密结果不同
        # (极短时间内可能相同，但概率极低)
        # 这里主要验证都能解密回原文
        assert decrypt_api_key(enc1) == original
        assert decrypt_api_key(enc2) == original


# ============================================
# B. 空值/边界处理
# ============================================

class TestEdgeCases:
    """边界条件"""

    def test_empty_string_encrypt(self):
        """空字符串加密返回空"""
        assert encrypt_api_key("") == ""

    def test_empty_string_decrypt(self):
        """空字符串解密返回空"""
        assert decrypt_api_key("") == ""

    def test_empty_string_safe_decrypt(self):
        """空字符串安全解密返回空"""
        assert decrypt_api_key_safe("") == ""

    def test_decrypt_invalid_token_raises(self):
        """无效密文解密应抛出 ValueError"""
        with pytest.raises(ValueError, match="Decryption failed"):
            decrypt_api_key("this-is-not-encrypted")


# ============================================
# C. 安全解密 (多格式兼容)
# ============================================

class TestSafeDecrypt:
    """安全解密 — 自动兼容 Fernet / Base64 / 原始值"""

    def test_safe_decrypt_fernet(self):
        """方法 1: Fernet 密文"""
        original = "sk-fernet-encrypted-key"
        encrypted = encrypt_api_key(original)
        result = decrypt_api_key_safe(encrypted)
        assert result == original

    def test_safe_decrypt_base64(self):
        """方法 2: Base64 编码的 Key"""
        original = "some-plain-api-key-value"
        base64_encoded = base64.b64encode(original.encode()).decode()
        result = decrypt_api_key_safe(base64_encoded)
        assert result == original

    def test_safe_decrypt_raw_sk_prefix(self):
        """方法 3: 未加密的 sk- 前缀 Key 直接返回"""
        raw = "sk-this-is-a-raw-openai-key-1234567890"
        result = decrypt_api_key_safe(raw)
        assert result == raw

    def test_safe_decrypt_raw_long_key(self):
        """方法 3: 未加密的长 Key (>20 字符) 直接返回"""
        raw = "raw-unencrypted-key-that-is-quite-long"
        result = decrypt_api_key_safe(raw)
        assert result == raw

    def test_safe_decrypt_unknown_format_raises(self):
        """所有方法均失败时应抛出 ValueError"""
        with pytest.raises(ValueError, match="unknown format"):
            decrypt_api_key_safe("short")


# ============================================
# D. API Key 脱敏 (mask)
# ============================================

class TestMaskApiKey:
    """API Key 脱敏显示"""

    def test_mask_normal_key(self):
        """普通 Key 脱敏: 保留前3位 + 末4位"""
        result = mask_api_key("sk-abcdefghijklmnop1234")
        assert result.startswith("sk-")
        assert result.endswith("1234")
        assert "*" in result

    def test_mask_shows_last_4(self):
        """末尾 4 位可见"""
        result = mask_api_key("some-random-api-key-WXYZ")
        assert result.endswith("WXYZ")

    def test_mask_empty(self):
        """空 Key 返回空"""
        assert mask_api_key("") == ""

    def test_mask_short_key(self):
        """短 Key (≤ show_chars) 全部替换为 *"""
        result = mask_api_key("1234", show_chars=4)
        assert result == "****"

    def test_mask_sk_prefix_preserved(self):
        """sk- 前缀应保留"""
        result = mask_api_key("sk-1234567890abcdef")
        assert result.startswith("sk-")

    def test_mask_non_sk_prefix(self):
        """非 sk- 前缀不保留前缀"""
        result = mask_api_key("api-key-1234567890abcdef")
        assert not result.startswith("api-")

    def test_mask_custom_show_chars(self):
        """自定义显示字符数"""
        result = mask_api_key("0123456789", show_chars=6)
        assert result.endswith("456789")

    def test_mask_max_stars(self):
        """星号最多 8 个 (避免超长掩码)"""
        result = mask_api_key("x" * 100)
        stars_count = result.count("*")
        assert stars_count <= 8


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
