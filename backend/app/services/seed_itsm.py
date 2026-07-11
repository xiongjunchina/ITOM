"""M2 种子：工单两套状态机、SLA 策略、流程定义、示例目录/服务项。幂等。"""
from sqlalchemy.orm import Session

from app.core.rbac import CIO, IS_MGR, IT_BM, IT_BP, IT_DEV, IT_OPS, IT_PDM, IT_TM
from app.models import (
    ProcessDefinition,
    ProcessStep,
    ServiceCatalog,
    ServiceItem,
    SlaPolicy,
    WorkflowStatus,
    WorkflowTransition,
)

# ---- 状态机（PRD §5.1）----

PROBLEM_STATUSES = [
    ("problem", "new", "新建", True, False, 1),
    ("problem", "analyzing", "分析中", False, False, 2),
    ("problem", "known_error", "已知错误", False, False, 3),
    ("problem", "resolved", "已解决", False, False, 4),
    ("problem", "closed", "已关闭", False, True, 5),
]

PROBLEM_TRANSITIONS = [
    ("problem", "new", "analyzing", []),
    ("problem", "analyzing", "known_error", []),
    ("problem", "known_error", "resolved", []),
    ("problem", "analyzing", "resolved", []),
    ("problem", "resolved", "closed", []),
    ("problem", "resolved", "analyzing", []),  # 复发重开
]

CI_CATEGORIES = [
    ("ci_category", "app", "应用", 1),
    ("ci_category", "server", "服务器", 2),
    ("ci_category", "cloud", "云资源", 3),
    ("ci_category", "network", "网络", 4),
    ("ci_category", "security", "安全", 5),
    ("ci_category", "collab", "协作", 6),
    ("ci_category", "euc", "终端", 7),
    ("ci_category", "infra", "基础设施", 8),
    ("ci_category", "consulting", "咨询服务", 9),
]

TICKET_STATUSES = [
    # (entity_type, code, name, initial, terminal, sort)
    ("ticket", "new", "新建", True, False, 1),
    ("ticket", "processing", "处理中", False, False, 2),
    ("ticket", "paused", "挂起", False, False, 3),
    ("ticket", "resolved", "已解决", False, False, 4),
    ("ticket", "closed", "已关闭", False, True, 5),
    ("ticket_change", "new", "新建", True, False, 1),
    ("ticket_change", "pending_approval", "待审批", False, False, 2),
    ("ticket_change", "approved", "已批准", False, False, 3),
    ("ticket_change", "rejected", "已拒绝", False, True, 4),
    ("ticket_change", "implementing", "实施中", False, False, 5),
    ("ticket_change", "rolled_back", "已回退", False, False, 6),
    ("ticket_change", "resolved", "已解决", False, False, 7),
    ("ticket_change", "closed", "已关闭", False, True, 8),
]

TICKET_TRANSITIONS = [
    # (entity_type, from, to, allowed_roles 空=不限)
    ("ticket", "new", "processing", []),
    ("ticket", "new", "resolved", []),          # 快速解决
    ("ticket", "processing", "paused", []),
    ("ticket", "paused", "processing", []),
    ("ticket", "processing", "resolved", []),
    ("ticket", "resolved", "processing", []),   # 重开
    ("ticket", "resolved", "closed", []),
    ("ticket_change", "new", "pending_approval", []),
    ("ticket_change", "pending_approval", "approved", [CIO, IT_TM]),
    ("ticket_change", "pending_approval", "rejected", [CIO, IT_TM]),
    ("ticket_change", "approved", "implementing", []),
    ("ticket_change", "implementing", "resolved", []),
    ("ticket_change", "implementing", "rolled_back", []),
    ("ticket_change", "rolled_back", "closed", []),
    ("ticket_change", "resolved", "closed", []),
]

SLA_POLICIES = [
    ("P1", 30, 4), ("P2", 60, 8), ("P3", 240, 24), ("P4", 480, 72),
]

# ITIL 4 实践 × 矩阵式组织（docs/06 §六）：
# 事件=快速恢复(运维处理,TM 复盘)；服务请求=标准交付(BP 对接用户确认)；
# 变更=风险评估(信息安全)→授权(CIO/TM)→实施(运维)→PIR 复盘(TM)；
# 问题=根因管理；需求=BP登记→产品分析→BM排期协调→开发→产品验收（M5 单据上线即挂接）
PROCESS_DEFS = [
    {
        "code": "incident_flow", "name": "事件处理流程", "entity_type": "ticket",
        "trigger": {"ticket_type": "incident"},
        "steps": [
            ("受理定级", IT_OPS, "L3", 0.5),
            ("诊断与处理", IT_OPS, "L3", None),
            ("解决与用户确认", IT_OPS, "L3", None),
            ("关闭复盘", IT_TM, "L2", 24),
        ],
    },
    {
        "code": "sr_flow", "name": "服务请求交付流程", "entity_type": "ticket",
        "trigger": {"ticket_type": "service_request"},
        "steps": [
            ("受理确认", IT_OPS, "L2", 4),
            ("实施交付", IT_OPS, "L3", None),
            ("用户确认关闭", IT_BP, "L3", 24),
        ],
    },
    {
        "code": "change_flow", "name": "变更管理流程", "entity_type": "ticket_change",
        "trigger": {"ticket_type": "change"},
        "steps": [
            ("变更登记与风险评估", IS_MGR, "L3", 8),
            ("变更审批", CIO, "L3", 24),
            ("实施与验证", IT_OPS, "L3", None),
            ("变更复盘(PIR)", IT_TM, "L2", 48),
        ],
    },
    {
        "code": "problem_flow", "name": "问题分析流程", "entity_type": "problem",
        "trigger": None,
        "steps": [
            ("问题确认", IT_OPS, "L3", 24),
            ("根因分析", IT_OPS, "L3", None),
            ("解决与验证", IT_OPS, "L3", None),
            ("关闭复盘", IT_TM, "L2", 48),
        ],
    },
    {
        "code": "requirement_flow", "name": "需求交付流程", "entity_type": "requirement",
        "trigger": None,
        "steps": [
            ("需求登记与业务对齐", IT_BP, "L3", 24),
            ("需求分析与方案", IT_PDM, "L3", None),
            ("排期与资源协调", IT_BM, "L3", 48),
            ("开发实现", IT_DEV, "L3", None),
            ("验收与关闭", IT_PDM, "L3", None),
        ],
    },
]


def run_seed_itsm(db: Session):
    from app.models import MasterData

    for category, code, name, sort in CI_CATEGORIES:
        if not db.query(MasterData).filter_by(category=category, code=code).first():
            db.add(MasterData(category=category, code=code, name=name, sort=sort))
    for etype, code, name, initial, terminal, sort in PROBLEM_STATUSES + TICKET_STATUSES:
        if not db.query(WorkflowStatus).filter_by(entity_type=etype, code=code).first():
            db.add(WorkflowStatus(entity_type=etype, code=code, name=name, is_initial=initial, is_terminal=terminal, sort=sort))
    for etype, frm, to, roles in PROBLEM_TRANSITIONS + TICKET_TRANSITIONS:
        if not db.query(WorkflowTransition).filter_by(entity_type=etype, from_code=frm, to_code=to).first():
            db.add(WorkflowTransition(entity_type=etype, from_code=frm, to_code=to, allowed_roles=roles))
    for priority, resp, reso in SLA_POLICIES:
        if not db.query(SlaPolicy).filter_by(priority=priority).first():
            db.add(SlaPolicy(priority=priority, response_minutes=resp, resolution_hours=reso))
    for d in PROCESS_DEFS:
        if not db.query(ProcessDefinition).filter_by(code=d["code"]).first():
            definition = ProcessDefinition(
                code=d["code"], name=d["name"], entity_type=d["entity_type"], trigger_condition=d["trigger"]
            )
            db.add(definition)
            db.flush()
            for seq, (name, role, level, sla_hours) in enumerate(d["steps"], start=1):
                db.add(ProcessStep(definition_id=definition.id, seq=seq, name=name, default_role=role, autonomy_level=level, sla_hours=sla_hours))
    # 示例目录/服务项：让系统开箱可报单，用户可改名或补充
    if not db.query(ServiceCatalog).first():
        catalog = ServiceCatalog(code="SC-INIT-0001", name="通用 IT 服务", tier="silver", description="初始目录，可编辑", sort=1)
        db.add(catalog)
        db.flush()
        db.add(
            ServiceItem(
                item_code="SI-INIT-0001", name="通用支持服务", catalog_id=catalog.id,
                service_type="日常运维", description="未细分服务项前的默认入口，可编辑",
            )
        )
    db.commit()
