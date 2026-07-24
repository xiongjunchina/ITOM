"""幂等种子数据：启动时执行（docs/05 §7）。"""
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rbac import ADMIN
from app.core.security import hash_password
from app.models import AuthUser, MasterData, Role

logger = logging.getLogger("aom.seed")

BUILTIN_ROLES = [
    ("admin", "系统管理员", "全部功能与系统配置（不入权限矩阵，隐式全权）"),
    ("cio", "CIO(IT总负责人)", "IT 整体负责：全业务读写、审批、团队管理域"),
    ("it_bm", "IT业务线负责人", "横向服务线：总体负责某业务域 IT 支持，对接需求/协调资源/过程管理（业务域负责人通常持此角色）"),
    ("it_tm", "IT专业线负责人", "纵向专业线：资源池统一管理/资源配置/培训与技能提升（用户组负责人通常持此角色）"),
    ("it_pdm", "IT产品经理", "专业线：需求分析/系统解决方案/排期/验收"),
    ("it_pdm_leader", "IT产品负责人", "产品经理团队 leader：需求方案评估主责、产品线规划"),
    ("it_pm", "IT项目经理", "专业线：项目创建与管理"),
    ("it_pmo", "IT PMO(项目管理办公室)", "项目治理：项目过程规范、组合监督、收尾复盘主持"),
    ("it_dev", "IT开发", "专业线：需求任务/WBS 任务/工单处理"),
    ("it_dev_leader", "IT开发负责人", "开发团队 leader：方案评估协同、开发任务清单管理与排期"),
    ("it_ops", "IT运维", "专业线：工单/变更实施/问题/CMDB/SLA"),
    ("it_op_leader", "IT运维负责人", "运维团队 leader：变更审批（变更经理）、事件关闭复盘、SLA 治理"),
    ("is_mgr", "信息安全管理员", "专业线：安全工单/变更复盘与安全审计/审计查看"),
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
    ("sys_config", "company_name", "我的公司", 1),
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
    from app.models import PointRule

    POINT_RULES = [
        ("idea_submit", "提出建言", 2),
        ("idea_like", "建言被点赞（每赞）", 1),
        ("idea_adopt", "建言被采纳", 20),
        ("ticket_resolved", "工单解决", 5),
        ("ticket_sla_met", "工单 SLA 双达成", 3),
        ("ticket_satisfaction", "满意度好评(≥4星)", 5),
        ("wbs_done_on_time", "项目任务按期完成", 5),
        ("milestone_achieved", "里程碑达成", 10),
        ("requirement_task_done", "需求任务完成", 5),
        ("requirement_closed", "需求关闭交付", 10),
        ("knowledge_published", "发表知识文章", 8),
        ("knowledge_voted", "知识被点有用（每次）", 2),
        ("training_host", "主讲/组织培训", 15),
        ("training_attend", "参与培训", 3),
    ]
    for code, name, points in POINT_RULES:
        rule = db.query(PointRule).filter(PointRule.code == code).first()
        if not rule:
            rule = PointRule(code=code, name=name, points=points)
            db.add(rule)
        if code in {"ticket_resolved", "ticket_sla_met", "ticket_satisfaction", "wbs_done_on_time",
                    "milestone_achieved", "requirement_task_done", "requirement_closed"}:
            rule.contribution_bucket = "role_result"
            rule.contribution_dimension = None
        else:
            rule.contribution_bucket = "team_contribution"
    if not db.query(AuthUser).filter(AuthUser.username == "admin").first():
        db.add(
            AuthUser(
                username="admin",
                password_hash=hash_password(settings.admin_init_password),
                roles=[ADMIN],
                is_active=True,
                password_set_at=datetime.now(),  # 初始口令为已知口令，本人改密需验当前密码
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


def run_seed_perf(db):
    """M6.1 人效计分方案参考模板（表空时写入一次，全部可编辑可删除）。"""
    from app.models import PerfScheme, Position

    if db.query(PerfScheme).first():
        return
    ops_pos = db.query(Position).filter(Position.name == "【示例】运维工程师", Position.is_deleted.is_(False)).first()
    db.add(PerfScheme(
        name="默认方案（兜底）", is_default=True,
        description="填写指引：未被任何方案匹配到岗位的人员按此方案计分。建议保留一个均衡配置作为兜底。",
        position_ids=[],
        dimensions=[
            {"code": "ticket_service", "weight": 20}, {"code": "change_compliance", "weight": 10},
            {"code": "project_delivery", "weight": 15}, {"code": "requirement_delivery", "weight": 15},
            {"code": "domain_satisfaction", "weight": 10}, {"code": "knowledge_contrib", "weight": 15},
            {"code": "activity_points", "weight": 15},
        ],
    ))
    db.add(PerfScheme(
        name="运维序列（参考模板）",
        description="填写指引：运维岗位以服务工单 + 变更合规为主，少量项目/需求参与。"
                    "已示例绑定【示例】运维工程师岗位，请改绑真实运维岗位并按贵司口径调整权重。",
        position_ids=[ops_pos.id] if ops_pos else [],
        dimensions=[
            {"code": "ticket_service", "weight": 40}, {"code": "change_compliance", "weight": 25},
            {"code": "project_delivery", "weight": 10}, {"code": "requirement_delivery", "weight": 5},
            {"code": "knowledge_contrib", "weight": 10}, {"code": "activity_points", "weight": 10},
        ],
    ))
    db.add(PerfScheme(
        name="研发/产品序列（参考模板）",
        description="填写指引：产品经理与开发以需求/项目交付 + 所在业务域满意度为主。"
                    "未绑定岗位前不生效，请在编辑中选择适用岗位（如产品经理/开发工程师）。",
        position_ids=[],
        dimensions=[
            {"code": "requirement_delivery", "weight": 35}, {"code": "project_delivery", "weight": 25},
            {"code": "domain_satisfaction", "weight": 15}, {"code": "knowledge_contrib", "weight": 10},
            {"code": "activity_points", "weight": 15},
        ],
    ))
    db.commit()


BPLUS_ROLE_PROFILES = [
    ("it_bm", "IT 业务线负责人", "business", "manager_review", [
        ("domain_demand_outcome", "业务需求结果", 40, "domain_demand_outcome"),
        ("internal_external_satisfaction", "内外部满意度", 30, "internal_external_satisfaction"),
        ("business_project_health", "业务域项目结果", 30, "project_manager_delivery"),
    ]),
    ("it_bp", "IT 业务合作伙伴", "business", "manager_review", [
        ("requirement_review_timeliness", "需求评审与验收", 40, "requirement_owner_delivery"),
        ("domain_demand_outcome", "业务需求结果", 30, "domain_demand_outcome"),
        ("internal_external_satisfaction", "内外部满意度", 30, "internal_external_satisfaction"),
    ]),
    ("it_tm", "IT 专业线负责人", "professional", "cio_direct", [
        ("team_delivery_outcome", "团队交付结果", 40, "team_delivery_outcome"),
        ("team_service_outcome", "团队服务结果", 30, "team_service_outcome"),
        ("professional_governance", "专业治理与培养", 30, "manual"),
    ]),
    ("it_pdm_leader", "IT 产品负责人", "professional", "cio_direct", [
        ("team_delivery_outcome", "团队交付结果", 45, "team_delivery_outcome"),
        ("domain_satisfaction", "业务满意度", 25, "domain_satisfaction"),
        ("professional_governance", "产品治理", 30, "manual"),
    ]),
    ("it_pdm", "IT 产品经理", "professional", "manager_review", [
        ("requirement_owner_delivery", "需求负责人交付", 45, "requirement_owner_delivery"),
        ("domain_satisfaction", "业务满意度", 30, "domain_satisfaction"),
        ("project_delivery", "关联项目交付", 25, "project_delivery"),
    ]),
    # PMO 自身由 CIO 直评；PMO 对 it_pm 资源池成员的初评范围由用户组 owner 形成。
    ("it_pmo", "IT PMO", "professional", "cio_direct", [
        ("process_task_timeliness", "流程治理及时性", 40, "process_task_timeliness"),
        ("project_manager_delivery", "项目治理结果", 35, "project_manager_delivery"),
        ("requirement_delivery", "需求/项目闭环", 25, "requirement_delivery"),
    ]),
    ("it_pm", "IT 项目经理", "professional", "manager_review", [
        ("project_manager_delivery", "项目经理交付", 55, "project_manager_delivery"),
        ("project_delivery", "项目任务与里程碑", 25, "project_delivery"),
        ("requirement_delivery", "关联需求闭环", 20, "requirement_delivery"),
    ]),
    ("it_dev_leader", "IT 开发负责人", "professional", "cio_direct", [
        ("team_delivery_outcome", "团队交付结果", 45, "team_delivery_outcome"),
        ("team_service_outcome", "团队质量结果", 25, "team_service_outcome"),
        ("professional_governance", "工程治理与培养", 30, "manual"),
    ]),
    ("it_dev", "IT 开发", "professional", "manager_review", [
        ("requirement_delivery", "需求交付", 45, "requirement_delivery"),
        ("project_delivery", "项目交付", 45, "project_delivery"),
        ("change_quality", "变更质量", 10, "change_compliance"),
    ]),
    ("it_op_leader", "IT 运维负责人", "professional", "cio_direct", [
        ("team_service_outcome", "团队服务结果", 50, "team_service_outcome"),
        ("change_compliance", "变更治理", 25, "change_compliance"),
        ("professional_governance", "运维治理与培养", 25, "manual"),
    ]),
    ("it_ops", "IT 运维", "professional", "manager_review", [
        ("ticket_service", "服务工单", 60, "ticket_service"),
        ("change_compliance", "变更合规", 30, "change_compliance"),
        ("domain_satisfaction", "业务满意度", 10, "domain_satisfaction"),
    ]),
    ("is_mgr", "信息安全与平台服务", "platform", "cio_direct", [
        ("security_governance", "信息安全治理", 40, "manual"),
        ("security_incident", "安全事件与风险", 30, "manual"),
        ("internal_external_satisfaction", "内部客户满意度", 30, "internal_external_satisfaction"),
    ]),
    ("data_governance", "数据治理/数据平台", "platform", "cio_direct", [
        ("data_quality_standard", "数据质量与标准", 40, "manual"),
        ("data_delivery", "数据交付", 30, "manual"),
        ("data_value", "数据价值", 30, "manual"),
    ]),
    ("ai", "AI 技术/智能化", "platform", "cio_direct", [
        ("ai_scenario_value", "AI 场景价值", 35, "manual"),
        ("ai_quality_security", "应用质量与安全", 35, "manual"),
        ("ai_delivery_adoption", "交付与采用", 30, "manual"),
    ]),
    ("architecture", "架构与平台服务", "platform", "cio_direct", [
        ("architecture_governance", "架构治理", 40, "manual"),
        ("platform_delivery", "平台能力与交付", 30, "manual"),
        ("internal_external_satisfaction", "内部客户满意度", 30, "internal_external_satisfaction"),
    ]),
]


def run_seed_perf_bplus(db: Session):
    """矩阵角色档案和维度种子：仅补齐缺失，不覆盖 CIO 已调整的规则。"""
    from app.models import PerformanceContributionConfig, PerformanceRoleDimension, PerformanceRoleProfile
    from app.services.perf_bplus import TEAM_TARGETS, TEAM_WEIGHTS

    if not db.query(PerformanceContributionConfig).filter(PerformanceContributionConfig.is_deleted.is_(False)).first():
        db.add(PerformanceContributionConfig(
            weights=dict(TEAM_WEIGHTS), targets=dict(TEAM_TARGETS),
            internal_satisfaction_weight=50, external_satisfaction_weight=50,
        ))

    for code, name, line_type, review_mode, dimensions in BPLUS_ROLE_PROFILES:
        profile = db.query(PerformanceRoleProfile).filter(PerformanceRoleProfile.role_code == code).first()
        if not profile:
            profile = PerformanceRoleProfile(
                role_code=code, name=name, line_type=line_type, review_mode=review_mode,
                description=f"矩阵角色评分档案：{name}", active=True,
            )
            db.add(profile)
            db.flush()
        elif profile.description and profile.description.startswith("B+ 矩阵角色评分档案："):
            # 清理早期种子写入的旧产品名，但不覆盖管理员后来编辑的其他描述。
            profile.description = profile.description.replace("B+ 矩阵角色评分档案：", "矩阵角色评分档案：", 1)
        for sort, (dimension_code, dimension_name, weight, metric) in enumerate(dimensions):
            dimension = db.query(PerformanceRoleDimension).filter(
                PerformanceRoleDimension.profile_id == profile.id,
                PerformanceRoleDimension.dimension_code == dimension_code,
            ).first()
            if not dimension:
                db.add(PerformanceRoleDimension(
                    profile_id=profile.id, dimension_code=dimension_code, name=dimension_name,
                    weight=weight, source_config={"metric": metric}, sort=sort, active=True,
                ))
    db.commit()
