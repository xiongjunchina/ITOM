"""基于部署 JWT 密钥派生 Fernet 密钥，对需回显/使用的集成秘密进行加密。"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.errors import AppError


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.jwt_secret.encode()).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str | None) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise AppError("SECRET_DECRYPT_FAILED", "系统密钥已变化，无法读取已保存的集成密钥，请重新配置", 500) from exc
