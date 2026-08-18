"""功能权限矩阵（docs/06 §七，M3.6）。

- 粒度：模块 × 动作（view 可见含查看 / create 新建 / edit 修改 / delete 删除）
- 矩阵只管"功能开关"；数据范围规则（如 requester 仅见自己的工单）仍由业务代码内置
- admin 永远全权且不可配置（防锁死）；仅持 auditor 的用户另受全局只读中间件约束
- 权限取用户 直接角色∪组授予角色 的矩阵并集（不含 base_role 运行时继承——
  自定义角色在创建时复制模板角色的矩阵，之后独立编辑）
- 流程/状态机的角色引用是另一层（workflow allowed_roles / process default_role），与本矩阵无关
"""
import logging

from sqlalchemy.orm import Session

from app.models import AuthUser, RolePermission, UserGroup, UserGroupMember

logger = logging.getLogger(__name__)

ACTIONS = ("view", "create", "edit", "delete")

# (module, 中文名, 分组)。i18n：前端按 module code 映射 en 文案（module.<code>），此处中文为准。
# 标签与左侧导航/子标签保持同步（2026-07-12 M7 同步）；一个模块可对应多个菜单入口（如 tickets 覆盖服务请求/事件/变更）。
MODULES = [
    ("dashboard", "总览", "总览"),
    # M17.2：工单按类型独立授权（业务用户仅服务请求，不可发起变更/登记事件）
    ("ticket_sr", "服务请求", "ITSM"),
    ("catalog", "服务目录", "ITSM"),
    ("cmdb", "CMDB", "ITSM"),
    ("sla", "SLA", "ITSM"),
    ("ticket_change", "变更管理", "ITSM"),
    ("ticket_incident", "事件管理", "ITSM"),
    ("problems", "问题管理", "ITSM"),
    ("vendors", "供应商管理", "ITSM"),
    ("contracts", "合同管理", "ITSM"),
    ("knowledge", "知识库", "ITSM"),
    ("projects", "项目管理（项目列表/项目组合）", "项目管理"),
    ("portfolio_governance", "组合治理（目标/成员/依赖）", "项目管理"),
    ("portfolio_scoring", "组合评分", "项目管理"),
    ("portfolio_decision", "组合决策与基线", "项目管理"),
    ("portfolio_resource", "组合资源承诺", "项目管理"),
    ("portfolio_audit", "组合治理审计", "项目管理"),
    # 需求域按菜单页独立授权；只有 BDO/授权 IT 角色可登记需求，不能查看任务跟踪/评分规则。
    ("requirements", "需求总览（登记/评审/方案）", "需求管理"),
    ("req_tasks", "任务跟踪", "需求管理"),
    ("req_scoring", "评分规则", "需求管理"),
    ("task_development", "开发任务", "任务管理"),
    ("task_bug", "Bug 修复", "任务管理"),
    ("task_delegated", "委派任务", "任务管理"),
    ("process_definitions", "流程定义", "流程中心"),
    ("process_monitor", "流程监控", "流程中心"),
    ("team_overview", "团队总览", "团队管理"),
    ("performance", "人效评分", "团队管理"),
    ("performance_result", "人效最终结果", "团队管理"),
    ("performance_review", "人效分级评审", "团队管理"),
    ("performance_external", "人效外部原数据", "团队管理"),
    ("performance_admin", "人效周期与规则", "团队管理"),
    ("positions", "岗位编制", "团队管理"),
    ("activities", "培训发展", "团队管理"),
    ("learning_growth", "学习成长", "团队管理"),
    ("ideas", "活动积分", "团队管理"),
    ("charter", "团队文化", "团队管理"),
    # 顺序按左侧导航「系统管理」二级页：组织管理 / 用户与组管理 / 角色与权限 / 数据字典 / 状态机 / 需求评分 / 审计
    ("admin_departments", "部门管理", "系统管理"),
    ("admin_members", "人员主数据", "系统管理"),
    ("admin_business_domains", "业务域", "系统管理"),
    ("admin_users", "用户管理", "系统管理"),
    ("admin_groups", "用户组", "系统管理"),
    ("admin_roles", "角色管理", "系统管理"),
    ("admin_provision", "开通规则", "系统管理"),
    ("admin_permissions", "权限配置", "系统管理"),
    ("admin_master_data", "数据字典", "系统管理"),
    ("admin_workflow", "状态机配置", "系统管理"),
    ("admin_feishu", "系统集成", "系统管理"),
    ("admin_ai", "AI 智能体", "系统管理"),
    ("admin_audit", "审计日志", "系统管理"),
    ("admin_ui_branding", "界面与品牌", "系统管理"),
]
MODULE_CODES = {m[0] for m in MODULES}

# 工单类型 → 权限模块（M17.2 拆分后按单据类型鉴权）
TICKET_TYPE_MODULE = {
    "service_request": "ticket_sr",
    "incident": "ticket_incident",
    "change": "ticket_change",
}

# 菜单页分层（权限配置页按左侧导航的二级页组织；仅对"一页含多权限项"的合并页设置，
# 其余模块=页 1:1 的不设，直接挂在分组下）。code 对应左侧导航的合并页。
PAGE_NAMES = {
    "admin_org": "组织管理",
    "admin_identity": "用户与组管理",
    "admin_access": "角色与权限",
}
MODULE_PAGES = {
    "admin_departments": "admin_org", "admin_members": "admin_org", "admin_business_domains": "admin_org",
    "admin_users": "admin_identity", "admin_groups": "admin_identity",
    "admin_roles": "admin_access", "admin_provision": "admin_access", "admin_permissions": "admin_access",
}

# 动作缩写：v=view c=create e=edit d=delete
_BUSINESS_VIEW = [
    "dashboard", "ticket_sr", "ticket_incident", "ticket_change", "catalog", "cmdb", "sla",
    "problems", "vendors", "contracts", "knowledge", "projects", "portfolio_governance", "requirements",
    "req_tasks", "req_scoring", "team_overview", "activities", "ideas", "charter",
    "task_development", "task_bug", "task_delegated",
]

def _staff_base() -> dict[str, str]:
    matrix = {m: "v" for m in _BUSINESS_VIEW}
    matrix.update({"ticket_sr": "vce", "ticket_incident": "vce", "ticket_change": "vce",
                   "knowledge": "vce", "requirements": "vc", "performance_result": "v",
    "activities": "vc", "learning_growth": "vced", "ideas": "vc",
    # IT 团队成员均可维护开发/Bug/委派任务；具体编辑、分派和删除仍由业务服务按数据范围控制。
    "task_development": "vce", "task_bug": "vce", "task_delegated": "vce"})
    return matrix


def _merge(base: dict[str, str], extra: dict[str, str]) -> dict[str, str]:
    out = dict(base)
    for k, v in extra.items():
        out[k] = "".join(sorted(set(out.get(k, "") + v)))
    return out


# 内置角色默认矩阵（编码当前系统行为；admin 不在矩阵中——隐式全权）
DEFAULT_MATRIX: dict[str, dict[str, str]] = {
    # M33：业务用户总览默认关闭（登录落点自动=服务请求）；IT 需求仅由 BDO 登记。
    "requester": {"ticket_sr": "vc", "knowledge": "v"},
    "bdo": {"ticket_sr": "vc", "knowledge": "v", "requirements": "vc"},
    "auditor": _merge(
        {m: "v" for m in _BUSINESS_VIEW},
        {"process_definitions": "v", "process_monitor": "v", "portfolio_audit": "v", "admin_audit": "v"},
    ),
    "it_dev": _staff_base(),
    "it_bp": _merge(_staff_base(), {"requirements": "e"}),
    "it_pdm": _merge(_staff_base(), {"requirements": "e", "task_bug": "vce"}),
    "it_pdm_leader": _merge(_staff_base(), {"requirements": "e", "req_tasks": "e", "task_bug": "vce",
                                             "process_monitor": "v", "performance_review": "vce"}),
    "it_dev_leader": _merge(_staff_base(), {"requirements": "e", "req_tasks": "e", "task_development": "vce",
                                             "task_bug": "vce", "task_delegated": "vce",
                                             "process_monitor": "v", "performance_review": "vce"}),
    # PM 可提交自己负责项目的目标贡献和跨项目依赖；评分由 BM/PMO 执行。
    "it_pm": _merge(_staff_base(), {"projects": "ce", "portfolio_governance": "vc", "portfolio_scoring": "v"}),
    "it_pmo": _merge(_staff_base(), {
        "projects": "ce", "portfolio_governance": "vce", "portfolio_scoring": "vce",
        "portfolio_decision": "v", "portfolio_resource": "vce", "portfolio_audit": "v",
        "process_monitor": "v", "performance": "v", "performance_review": "vce",
    }),
    "it_ops": _merge(_staff_base(), {"problems": "ce", "cmdb": "ce", "vendors": "ce", "contracts": "ce"}),
    "it_op_leader": _merge(_staff_base(), {"problems": "ce", "cmdb": "ce", "vendors": "ce",
                                           "contracts": "ce", "sla": "e", "process_monitor": "v", "performance_review": "vce"}),
    "is_mgr": _merge(_staff_base(), {"problems": "ce", "cmdb": "ce", "admin_audit": "v"}),
    # 矩阵式组织三角色（docs/06 §七）——默认值是起点，全部可在权限配置页调整
    "cio": _merge(_staff_base(), {
        "catalog": "ce", "cmdb": "ce", "problems": "ce", "vendors": "ce", "contracts": "ce",
        "projects": "ce", "requirements": "e", "positions": "vced", "activities": "e",
        "portfolio_governance": "vce", "portfolio_scoring": "vce", "portfolio_decision": "vce",
        "portfolio_resource": "vced", "portfolio_audit": "v",
        "ideas": "e", "charter": "e", "sla": "e",
        "performance": "vce", "performance_review": "vce", "performance_external": "vced",
        "performance_admin": "vce", "process_definitions": "v", "process_monitor": "v",
        "admin_business_domains": "vce", "admin_members": "vced", "admin_audit": "v",
    }),
    "it_bm": _merge(_staff_base(), {
        "requirements": "e", "projects": "ce", "portfolio_governance": "v",
        "portfolio_scoring": "vce", "portfolio_audit": "v", "admin_business_domains": "v",
        "performance": "vce", "performance_review": "vce", "process_monitor": "v",
    }),
    "it_tm": _merge(_staff_base(), {
        "activities": "e", "charter": "e", "portfolio_governance": "v",
        "portfolio_resource": "vced", "portfolio_audit": "v", "performance": "vce", "performance_review": "vce",
        "learning_growth": "vced", "ideas": "e", "process_monitor": "v", "admin_members": "vce",
    }),
}

_FLAG = {"v": "view", "c": "create", "e": "edit", "d": "delete"}


def flags_to_actions(flags: str) -> list[str]:
    return [_FLAG[f] for f in flags if f in _FLAG]


def seed_permissions(db: Session):
    """按角色写入默认矩阵并收敛受限内置角色的历史越权。

    一般情况下仅补种缺失模块，管理员已调整的矩阵不受影响。例外包括：
    ``requester → requirements`` 是已废止的业务用户需求登记入口，必须在启动时
    幂等移除；以及历史内置 IT 角色的 ``task_development`` 只有查看权限，需
    补齐为登记/修改所需的 ``view/create/edit``。两者均不修改业务数据。
    """
    removed = (
        db.query(RolePermission)
        .filter(
            RolePermission.role_code == "requester",
            RolePermission.module == "requirements",
            RolePermission.is_deleted.is_(False),
        )
        .delete(synchronize_session=False)
    )
    if removed:
        logger.info("removed deprecated requester requirements permission rows: %d", removed)
    for role_code, modules in DEFAULT_MATRIX.items():
        existing = {r.module for r in db.query(RolePermission).filter(RolePermission.role_code == role_code)}
        for module, flags in modules.items():
            if module not in existing:
                db.add(RolePermission(role_code=role_code, module=module, actions=flags_to_actions(flags)))
    # M104：已发布环境中的内置 IT 角色早已存在，单纯补种无法提升其已有
    # task_development 行。仅收敛这些内置 IT 角色的该模块，管理员角色仍为
    # 隐式全权，业务角色与自定义角色不受影响。
    it_role_codes = [
        role_code
        for role_code in DEFAULT_MATRIX
        if role_code == "cio" or role_code == "is_mgr" or role_code.startswith("it_")
    ]
    for permission in (
        db.query(RolePermission)
        .filter(
            RolePermission.role_code.in_(it_role_codes),
            RolePermission.module == "task_development",
            RolePermission.is_deleted.is_(False),
        )
        .all()
    ):
        permission.actions = flags_to_actions("vce")
    db.commit()


def user_permissions(db: Session, user: AuthUser) -> dict[str, list[str]]:
    """{module: [actions]}；admin 返回 {"*": 全部}。取直接角色∪组授予角色的矩阵并集。"""
    roles: set[str] = set(user.roles or [])
    if user.person_id:
        groups = (
            db.query(UserGroup)
            .join(UserGroupMember, UserGroupMember.group_id == UserGroup.id)
            .filter(
                UserGroupMember.person_id == user.person_id,
                UserGroupMember.is_deleted.is_(False),
                UserGroup.is_deleted.is_(False),
            )
            .all()
        )
        for g in groups:
            roles |= set(g.roles or [])
    if "admin" in roles:
        return {"*": list(ACTIONS)}
    if not roles:
        return {}
    rows = (
        db.query(RolePermission)
        .filter(RolePermission.role_code.in_(roles), RolePermission.is_deleted.is_(False))
        .all()
    )
    merged: dict[str, set[str]] = {}
    for r in rows:
        merged.setdefault(r.module, set()).update(r.actions or [])
    return {m: sorted(a) for m, a in merged.items()}


def has_perm(db: Session, user: AuthUser, module: str, action: str) -> bool:
    perms = user_permissions(db, user)
    if "*" in perms:
        return True
    return action in perms.get(module, [])
