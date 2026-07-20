"""系统集成配置单行记录。"""
from sqlalchemy.orm import Session
from app.models import SystemIntegrationConfig


def get_integration_config(db: Session) -> SystemIntegrationConfig:
    row = db.query(SystemIntegrationConfig).filter(SystemIntegrationConfig.is_deleted.is_(False)).first()
    if not row:
        row = SystemIntegrationConfig(email_config={}, ldap_config={})
        db.add(row); db.flush()
    return row
