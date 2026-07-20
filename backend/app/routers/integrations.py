"""系统集成：邮件服务器与 AD/LDAP 全局配置。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_roles
from app.schemas.common import ok
from app.services.audit import audit
from app.services.integrations import get_integration_config
from app.services.secrets_store import encrypt_secret

router = APIRouter(prefix="/api/admin/integrations", tags=["admin"])


class EmailConfigIn(BaseModel):
    enabled: bool = False
    host: str = ""
    port: int = Field(default=587, ge=1, le=65535)
    username: str = ""
    password: str | None = None
    from_email: str = ""
    from_name: str = "ITOM"
    use_tls: bool = True


class LdapConfigIn(BaseModel):
    enabled: bool = False
    server_url: str = ""
    bind_dn: str = ""
    bind_password: str | None = None
    base_dn: str = ""
    user_dn_template: str = "{username}"
    use_ssl: bool = False


def _public(cfg: dict, secret_key: str) -> dict:
    return {**{k: v for k, v in cfg.items() if k != secret_key}, "has_secret": bool(cfg.get(secret_key))}


@router.get("/email")
def get_email(db: Session = Depends(get_db), _=Depends(require_roles("admin"))):
    return ok(_public(get_integration_config(db).email_config or {}, "password_encrypted"))


@router.put("/email")
def put_email(body: EmailConfigIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin"))):
    row = get_integration_config(db); old = row.email_config or {}
    data = body.model_dump(exclude={"password"})
    data["password_encrypted"] = encrypt_secret(body.password) if body.password else old.get("password_encrypted")
    row.email_config = data
    audit(db, "system_integration", row.id, "update_email", actor, {"fields": list(data)})
    db.commit(); return ok(_public(data, "password_encrypted"))


@router.post("/email/test")
def test_email(db: Session = Depends(get_db), actor=Depends(require_roles("admin"))):
    email = actor.person.email if actor.person else None
    if not email: from app.core.errors import AppError; raise AppError("EMAIL_REQUIRED", "当前管理员未关联有效邮箱，无法发送测试邮件")
    from app.services.email import send_initial_password_email
    send_initial_password_email(db, email, actor.name if hasattr(actor, "name") else actor.username, actor.username, "******")
    return ok({"sent_to": email})


@router.get("/ldap")
def get_ldap(db: Session = Depends(get_db), _=Depends(require_roles("admin"))):
    return ok(_public(get_integration_config(db).ldap_config or {}, "bind_password_encrypted"))


@router.put("/ldap")
def put_ldap(body: LdapConfigIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin"))):
    row = get_integration_config(db); old = row.ldap_config or {}
    data = body.model_dump(exclude={"bind_password"})
    data["bind_password_encrypted"] = encrypt_secret(body.bind_password) if body.bind_password else old.get("bind_password_encrypted")
    row.ldap_config = data
    audit(db, "system_integration", row.id, "update_ldap", actor, {"fields": list(data)})
    db.commit(); return ok(_public(data, "bind_password_encrypted"))


@router.post("/ldap/test")
def ldap_test(db: Session = Depends(get_db), _=Depends(require_roles("admin"))):
    from app.services.ldap_auth import test_ldap
    test_ldap(db); return ok({"connected": True})
