"""M2 种子：工单两套状态机、SLA 策略、流程定义、示例目录/服务项。幂等。"""
from sqlalchemy.orm import Session

from app.core.rbac import IS_MGR, IT_OPS, MANAGER
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
    ("ticket_change", "pending_approval", "approved", [MANAGER]),
    ("ticket_change", "pending_approval", "rejected", [MANAGER]),
    ("ticket_change", "approved", "implementing", []),
    ("ticket_change", "implementing", "resolved", []),
    ("ticket_change", "implementing", "rolled_back", []),
    ("ticket_change", "rolled_back", "closed", []),
    ("ticket_change", "resolved", "closed", []),
]

SLA_POLICIES = [
    ("P1", 30, 4), ("P2", 60, 8), ("P3", 240, 24), ("P4", 480, 72),
]

PROCESS_DEFS = [
    {
        "code": "incident_flow", "name": "事件处理流程", "entity_type": "ticket",
        "trigger": {"ticket_type": "incident"},
        "steps": [
            ("受理定级", IT_OPS, "L3", 0.5),
            ("诊断与处理", IT_OPS, "L3", None),
            ("解决确认", IT_OPS, "L3", None),
            ("关闭回访", IT_OPS, "L2", 24),
        ],
    },
    {
        "code": "sr_flow", "name": "服务请求交付流程", "entity_type": "ticket",
        "trigger": {"ticket_type": "service_request"},
        "steps": [
            ("受理确认", IT_OPS, "L2", 4),
            ("实施交付", IT_OPS, "L3", None),
            ("确认关闭", IT_OPS, "L3", 24),
        ],
    },
    {
        "code": "change_flow", "name": "变更管理流程", "entity_type": "ticket_change",
        "trigger": {"ticket_type": "change"},
        "steps": [
            ("提交与风险评估", IS_MGR, "L3", 8),
            ("变更审批", MANAGER, "L3", 24),
            ("实施与验证", IT_OPS, "L3", None),
            ("关闭复盘", IT_OPS, "L2", 48),
        ],
    },
]


def run_seed_itsm(db: Session):
    for etype, code, name, initial, terminal, sort in TICKET_STATUSES:
        if not db.query(WorkflowStatus).filter_by(entity_type=etype, code=code).first():
            db.add(WorkflowStatus(entity_type=etype, code=code, name=name, is_initial=initial, is_terminal=terminal, sort=sort))
    for etype, frm, to, roles in TICKET_TRANSITIONS:
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
