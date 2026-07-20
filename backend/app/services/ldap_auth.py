"""AD/LDAP 连接测试与认证。"""
from ldap3 import Connection, Server, Tls
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.services.integrations import get_integration_config
from app.services.secrets_store import decrypt_secret


def _connection(cfg: dict, user: str, password: str) -> Connection:
    server = Server(cfg["server_url"], use_ssl=bool(cfg.get("use_ssl")), connect_timeout=10)
    return Connection(server, user=user, password=password, auto_bind=True, receive_timeout=10)


def test_ldap(db: Session) -> None:
    cfg = get_integration_config(db).ldap_config or {}
    if not cfg.get("server_url") or not cfg.get("bind_dn"):
        raise AppError("LDAP_NOT_CONFIGURED", "请先填写 LDAP 服务器与绑定账号")
    try:
        conn = _connection(cfg, cfg["bind_dn"], decrypt_secret(cfg.get("bind_password_encrypted")))
        conn.unbind()
    except Exception as exc:
        raise AppError("LDAP_CONNECT_FAILED", "AD/LDAP 连接或绑定失败", 502) from exc


def authenticate_ldap(db: Session, username: str, password: str) -> bool:
    cfg = get_integration_config(db).ldap_config or {}
    if not cfg.get("enabled"):
        return False
    user_dn = (cfg.get("user_dn_template") or "{username}").replace("{username}", username)
    try:
        conn = _connection(cfg, user_dn, password)
        conn.unbind()
        return True
    except Exception:
        return False
