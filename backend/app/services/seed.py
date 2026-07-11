"""幂等种子数据：启动时执行（docs/05 §7）。"""
import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rbac import ADMIN
from app.core.security import hash_password
from app.models import AuthUser, MasterData, Role

logger = logging.getLogger("aom.seed")

BUILTIN_ROLES = [
    ("admin", "系统管理员", "全部功能与系统配置（不入权限矩阵，隐式全权）"),
    ("cio", "CIO(IT总负责人)", "IT 整体负责：全业务读写、审批、团队管理域"),
    ("manager", "团队负责人(通用)", "通用管理角色，兼容保留；矩阵组织下建议使用 CIO/IT BM/IT TM"),
    ("it_bm", "IT业务线负责人", "横向服务线：总体负责某业务域 IT 支持，对接需求/协调资源/过程管理（业务域负责人通常持此角色）"),
    ("it_tm", "IT专业线负责人", "纵向专业线：资源池统一管理/资源配置/培训与技能提升（用户组负责人通常持此角色）"),
    ("it_pdm", "IT产品经理", "专业线：需求分析/系统解决方案/排期/验收"),
    ("it_pm", "IT项目经理", "专业线：项目创建与管理"),
    ("it_dev", "IT开发", "专业线：需求任务/WBS 任务/工单处理"),
    ("it_ops", "IT运维", "专业线：工单/变更实施/问题/CMDB/SLA"),
    ("is_mgr", "信息安全管理员", "专业线：安全工单/变更风险评估/审计查看"),
    ("it_bp", "IT业务合作伙伴", "服务线成员：需求登记与业务对齐/代提单"),
    ("auditor", "审计员", "全模块只读 + 审计日志查看，不可修改任何单据"),
    ("requester", "业务用户", "提交工单和需求、查询自己的单据、满意度评价"),
]

DEFAULT_PROVISION_RULES = [
    # (match_type, match_value, default_roles, sort) 仅账号首次开通生效
    ("dept_type", "business", ["requester"], 10),
    ("dept_type", "audit", ["requester"], 20),   # 审计部门默认也是业务用户；auditor 由管理员手工授予
    ("dept_type", "it", ["requester"], 30),      # IT 新人先基础权限，管理员再细分
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
    from app.models import ProvisionRule

    for code, name, desc in BUILTIN_ROLES:
        if not db.query(Role).filter(Role.code == code).first():
            db.add(Role(code=code, name=name, description=desc, is_builtin=True))
    if not db.query(ProvisionRule).first():
        for match_type, match_value, roles, sort in DEFAULT_PROVISION_RULES:
            db.add(ProvisionRule(match_type=match_type, match_value=match_value, default_roles=roles, sort=sort))
    from app.services.permissions import seed_permissions

    seed_permissions(db)
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
