"""幂等种子数据：启动时执行（docs/05 §7）。"""
import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rbac import ADMIN
from app.core.security import hash_password
from app.models import AuthUser, MasterData

logger = logging.getLogger("aom.seed")

MASTER_DATA = [
    # (category, code, name, sort)
    ("business_line", "internal_it", "内部 IT", 1),
    ("business_line", "data_platform", "数据平台", 2),
    ("business_line", "infra", "基础设施", 3),
    ("closure_code", "resolved", "已解决", 1),
    ("closure_code", "workaround", "临时规避", 2),
    ("closure_code", "not_reproducible", "无法复现", 3),
    ("closure_code", "duplicate", "重复单", 4),
    ("closure_code", "cancelled", "取消", 5),
    ("requirement_source", "biz_dept", "业务部门", 1),
    ("requirement_source", "management", "管理层", 2),
    ("requirement_source", "team_internal", "团队内部", 3),
    ("requirement_source", "idea_adopted", "建言采纳", 4),
]


def run_seed(db: Session):
    if not db.query(AuthUser).filter(AuthUser.username == "admin").first():
        db.add(
            AuthUser(
                username="admin",
                password_hash=hash_password(settings.admin_init_password),
                roles=[ADMIN],
                is_active=True,
            )
        )
        logger.info("seeded admin user")
    for category, code, name, sort in MASTER_DATA:
        exists = (
            db.query(MasterData)
            .filter(MasterData.category == category, MasterData.code == code)
            .first()
        )
        if not exists:
            db.add(MasterData(category=category, code=code, name=name, sort=sort))
    db.commit()
