"""幂等种子数据：启动时执行（docs/05 §7）。"""
import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rbac import ADMIN
from app.core.security import hash_password
from app.models import AuthUser, MasterData, Role

logger = logging.getLogger("aom.seed")

BUILTIN_ROLES = [
    ("admin", "系统管理员", "全部功能与系统配置"),
    ("manager", "团队负责人", "全部业务 + 团队管理 + 变更审批 + 建言采纳"),
    ("it_pdm", "IT产品经理", "侧重需求域：需求分析/排期/验收/关闭"),
    ("it_pm", "IT项目经理", "侧重项目域：项目创建与管理"),
    ("it_dev", "IT开发", "侧重交付：需求任务/WBS 任务/工单处理"),
    ("it_ops", "IT运维", "侧重运维：工单/变更实施/问题/CMDB/SLA"),
    ("is_mgr", "信息安全管理员", "安全治理：安全工单/变更风险评估/审计查看"),
    ("it_bp", "IT业务合作伙伴", "业务接口：需求登记与业务对齐/代提单"),
    ("requester", "业务用户", "提交工单和需求、查询自己的单据、满意度评价"),
]

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
    for code, name, desc in BUILTIN_ROLES:
        if not db.query(Role).filter(Role.code == code).first():
            db.add(Role(code=code, name=name, description=desc, is_builtin=True))
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
