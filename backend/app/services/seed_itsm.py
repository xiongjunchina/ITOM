"""M2 种子：工单两套状态机、SLA 策略、流程定义、示例目录/服务项。幂等。"""
from sqlalchemy.orm import Session

from app.core.rbac import CIO, IS_MGR, IT_BM, IT_BP, IT_DEV, IT_OPS, IT_PDM, IT_PM, IT_TM, IT_PMO, IT_PDM_LEADER, IT_DEV_LEADER, IT_OP_LEADER
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

PROJECT_STATUSES = [
    ("project", "planning", "规划中", True, False, 1),
    ("project", "active", "进行中", False, False, 2),
    ("project", "paused", "已暂停", False, False, 3),
    ("project", "completed", "已完成", False, False, 4),
    ("project", "closed", "已关闭", False, True, 5),
    ("project", "cancelled", "已取消", False, True, 6),
]

PROJECT_TRANSITIONS = [
    ("project", "planning", "active", []),
    ("project", "active", "paused", []),
    ("project", "paused", "active", []),
    ("project", "active", "completed", []),
    ("project", "completed", "closed", []),
    ("project", "active", "closed", []),      # 提前关闭（M14 列表快捷操作）
    ("project", "paused", "closed", []),
    ("project", "planning", "cancelled", []),
    ("project", "active", "cancelled", []),
    # 恢复类流转（2026-07-14）：终态/已完成可重启，误关闭可纠正
    ("project", "closed", "active", []),      # 已关闭 → 重新启动
    ("project", "completed", "active", []),   # 已完成 → 重新打开（返工）
    ("project", "cancelled", "planning", []), # 已取消 → 重新规划
]

REQUIREMENT_STATUSES = [
    ("requirement", "registered", "已登记", True, False, 1),
    ("requirement", "evaluating", "评估中", False, False, 2),
    ("requirement", "analyzing", "分析中", False, False, 3),
    ("requirement", "implementing", "实现中", False, False, 4),
    ("requirement", "closed", "已关闭", False, True, 5),
    ("requirement", "on_hold", "已搁置", False, False, 6),
    ("requirement", "cancelled", "已取消", False, True, 7),
]

REQUIREMENT_TRANSITIONS = [
    # 主漏斗：登记 → 评估 → 分析 → 实现 → 关闭
    ("requirement", "registered", "evaluating", []),
    ("requirement", "evaluating", "analyzing", []),   # 评估门：需决议=立项（service 校验）
    ("requirement", "registered", "analyzing", []),   # 小需求可跳过评估
    ("requirement", "analyzing", "implementing", []),
    ("requirement", "implementing", "closed", []),
    # 搁置/驳回/取消
    ("requirement", "registered", "on_hold", []),
    ("requirement", "evaluating", "on_hold", []),
    ("requirement", "analyzing", "on_hold", []),
    ("requirement", "implementing", "on_hold", []),
    ("requirement", "on_hold", "evaluating", []),
    ("requirement", "on_hold", "analyzing", []),
    ("requirement", "registered", "cancelled", []),
    ("requirement", "evaluating", "cancelled", []),
    ("requirement", "analyzing", "cancelled", []),
    ("requirement", "on_hold", "cancelled", []),
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
    ("ticket_change", "pending_approval", "approved", [CIO, IT_TM, IT_OP_LEADER]),
    ("ticket_change", "pending_approval", "rejected", [CIO, IT_TM, IT_OP_LEADER]),
    ("ticket_change", "approved", "implementing", []),
    ("ticket_change", "implementing", "resolved", []),
    ("ticket_change", "implementing", "rolled_back", []),
    ("ticket_change", "rolled_back", "closed", []),
    ("ticket_change", "resolved", "closed", []),
]

SLA_POLICIES = [
    ("P1", 30, 4), ("P2", 60, 8), ("P3", 240, 24), ("P4", 480, 72),
]

# P1-P4 优先级定义初稿（M29，参考 ITIL 4「影响×紧急度」矩阵与 ServiceNow 缺省实践）；管理员可在 SLA 页编辑适配企业实际
PRIORITY_DEFINITIONS = [
    # (flow_type, priority, definition, examples)
    ("incident", "P1", "致命：核心业务系统全面中断或存在数据丢失风险，影响全公司或对外服务，且无可用替代方案。需立即响应、专人全程跟进，必要时启动重大事件流程并通报管理层。",
     "ERP/订单系统全面宕机；机房断电断网；生产数据库损坏；对外服务大面积不可用"),
    ("incident", "P2", "严重：核心系统部分功能不可用或性能严重下降，影响某业务域多数用户；存在临时绕行方案但代价较高。优先处理，持续同步进展。",
     "订单接口批量超时；仓库扫描枪集体离线但可手工录入；某分公司网络中断"),
    ("incident", "P3", "一般：非核心功能故障或个别用户受阻，业务整体可继续运转。按 SLA 正常排队处理。",
     "个别用户无法打印；单个账号异常锁定；报表偶发打开缓慢"),
    ("incident", "P4", "轻微：外观、体验类问题或使用咨询，几乎不影响业务，可计划性安排处理。",
     "页面显示错位；提示文案错误；功能使用方法咨询"),
    ("service_request", "P1", "紧急：影响业务开展或关键岗位/高管的开通、权限、配置类请求，需当日完成；通常伴随明确的业务截止时间。",
     "新高管入职账号全套开通；投标截止前的系统权限开通；月结前财务系统配置调整"),
    ("service_request", "P2", "高：影响部门级工作效率的请求，需要优先安排。",
     "部门批量账号开通；共享盘扩容；常用系统配置调整"),
    ("service_request", "P3", "普通：常规单人请求，按服务目录承诺时限排期交付。",
     "软件安装；单人权限申请；邮箱容量调整"),
    ("service_request", "P4", "低：非急需的物品/配置请求或改进建议，可纳入计划批量处理。",
     "外设更换预约；桌面壁纸/签名规范咨询；体验优化建议"),
    ("change", "P1", "紧急变更：为修复 P1/P2 事件或封堵重大安全漏洞而必须立即实施的变更。走紧急审批通道（可事后补审），必须有回退方案，实施后 48 小时内完成复盘。",
     "生产库紧急扩容；高危漏洞紧急补丁；核心服务紧急回滚"),
    ("change", "P2", "高风险变更：影响核心系统或跨多业务域的重大版本升级、架构调整。需完整评审、变更窗口与回退演练，相关方提前知会。",
     "ERP 大版本升级；数据库迁移；网络架构调整"),
    ("change", "P3", "常规变更：影响面可控的普通发布或配置变更，走标准审批流程，在变更窗口内实施。",
     "业务系统常规迭代发布；防火墙策略调整；中间件参数变更"),
    ("change", "P4", "标准变更：风险低、步骤固化、已预授权的例行操作，按模板执行，免逐次审批但留痕。",
     "例行补丁；证书更换；账号例行回收"),
    ("problem", "P1", "重大问题：已引发或极可能再次引发 P1 级事件的根因，重复造成核心业务中断。需立项根治、升级管理层跟踪，未解决期间维持临时措施并持续监控。",
     "反复导致核心系统宕机的底层缺陷；无法定位的间歇性数据错乱"),
    ("problem", "P2", "高影响问题：重复引发 P2 级事件，或已知错误波及多个系统/业务域。优先安排根因分析并明确修复计划。",
     "每逢月结高峰即出现的性能瓶颈；多系统共用组件的兼容缺陷"),
    ("problem", "P3", "一般问题：偶发且影响有限，安排常规根因分析，确认后纳入已知错误库并给出规避方案。",
     "低频出现的接口重试；特定操作序列触发的小故障"),
    ("problem", "P4", "低影响问题：轻微隐患或优化类问题，视资源情况列入技术改进计划。",
     "日志噪音治理；非关键任务的偶发告警"),
]

# ITIL 4 实践 × 矩阵式组织（docs/06 §六）：
# 事件=快速恢复(运维处理,TM 复盘)；服务请求=标准交付(BP 对接用户确认)；
# 变更=风险评估(信息安全)→授权(CIO/TM)→实施(运维)→PIR 复盘(TM)；
# 问题=根因管理；需求=BP登记→产品分析→BM排期协调→开发→产品验收（M5 单据上线即挂接）
PROCESS_DEFS = [
    {
        # 用户调试版（M33 固化）：受理定级由 IT 运维负责人把关
        "code": "incident_flow", "name": "事件处理流程", "entity_type": "ticket",
        "trigger": {"ticket_type": "incident"},
        "steps": [
            ("受理定级", IT_OP_LEADER, "L3", 0.5),
            ("诊断与处理", IT_OPS, "L3", None),
            ("解决与用户确认", IT_OPS, "L3", None),
            ("关闭复盘", IT_OP_LEADER, "L2", 24),
        ],
    },
    {
        # 用户调试版（M33 固化）：最后一步指派登记人本人确认（default_role=requester 动态解析）
        "code": "sr_flow", "name": "服务请求交付流程", "entity_type": "ticket",
        "trigger": {"ticket_type": "service_request"},
        "steps": [
            ("受理确认", IT_OPS, "L2", 4),
            ("实施交付", IT_OPS, "L3", None),
            ("用户确认关闭", "requester", "L3", 24),
        ],
    },
    {
        # 用户调试版（M33 固化）：登记与风险评估拆分为两步
        "code": "change_flow", "name": "变更管理流程", "entity_type": "ticket_change",
        "trigger": {"ticket_type": "change"},
        "steps": [
            ("变更登记", IT_OPS, "L3", None),
            ("风险评估", IS_MGR, "L3", 8, [IT_TM]),
            ("变更审批", CIO, "L3", 24, [IT_BM]),
            ("实施与验证", IT_OPS, "L3", None, [IS_MGR, IT_BM]),
            ("变更复盘(PIR)", IT_OP_LEADER, "L2", 48, [CIO]),
        ],
    },
    {
        # M29 重构：确认(专业线负责人,可驳回退回提单人)→根因分析(负责人转派处理人)→
        # 解决与验证(延续处理人)→解决确认与关闭(负责人登记关闭说明,完成自动关闭)
        "code": "problem_flow", "name": "问题分析流程", "entity_type": "problem",
        "trigger": None,
        "steps": [
            ("问题确认", None, "L3", 24, [], "按问题所属专业线自动指派对应负责人；不属实可驳回退回提单人（必填理由）"),
            ("根因分析", None, "L3", None, [], "确认属实时由专业线负责人指定处理人"),
            ("解决与验证", None, "L3", None, [], "延续根因分析处理人"),
            ("解决确认与关闭", None, "L2", 24, [], "专业线负责人确认已解决并登记关闭说明，完成后问题自动关闭"),
        ],
    },
    {
        "code": "project_flow", "name": "项目关键节点流程", "entity_type": "project",
        "trigger": None,
        "steps": [
            ("立项启动", IT_PM, "L3", 72, [CIO, IT_BM]),
            ("执行监控", IT_PM, "L3", None, []),
            ("收尾复盘", IT_PMO, "L2", 72, [CIO, IT_TM]),
        ],
    },
    {
        # M16 重构：登记即进评审（评审任务动态指派业务域 owner）→ 方案评估（产品 leader
        # 主责/开发 leader 知会，评分规则页可配）→ 实现交付（二开任务清单 或 转项目跟踪）→ 验收闭环
        "code": "requirement_flow", "name": "需求交付流程", "entity_type": "requirement",
        "trigger": None,
        "steps": [
            ("需求评审（业务域负责人）", IT_BM, "L3", 48, [IT_PDM]),
            ("方案评估与路径判定", IT_PDM_LEADER, "L3", 72, [IT_DEV_LEADER]),
            ("实现交付（转开发实现 / 转项目管理）", IT_DEV_LEADER, "L3", None, [],
             "两种路径由方案评估判定并自动指派：转开发实现→开发负责人（任务清单排期交付）；转项目管理→项目经理（项目立项交付，验收关闭后回传）"),
            ("验收与闭环", IT_BM, "L3", 48),
        ],
    },
]


def run_seed_itsm(db: Session):
    from app.models import MasterData

    for category, code, name, sort in CI_CATEGORIES:
        if not db.query(MasterData).filter_by(category=category, code=code).first():
            db.add(MasterData(category=category, code=code, name=name, sort=sort))
    for etype, code, name, initial, terminal, sort in PROBLEM_STATUSES + TICKET_STATUSES + PROJECT_STATUSES + REQUIREMENT_STATUSES:
        if not db.query(WorkflowStatus).filter_by(entity_type=etype, code=code).first():
            db.add(WorkflowStatus(entity_type=etype, code=code, name=name, is_initial=initial, is_terminal=terminal, sort=sort))
    for etype, frm, to, roles in PROBLEM_TRANSITIONS + TICKET_TRANSITIONS + PROJECT_TRANSITIONS + REQUIREMENT_TRANSITIONS:
        if not db.query(WorkflowTransition).filter_by(entity_type=etype, from_code=frm, to_code=to).first():
            db.add(WorkflowTransition(entity_type=etype, from_code=frm, to_code=to, allowed_roles=roles))
    for priority, resp, reso in SLA_POLICIES:
        if not db.query(SlaPolicy).filter_by(priority=priority).first():
            db.add(SlaPolicy(priority=priority, response_minutes=resp, resolution_hours=reso))
    from app.models import SlaPriorityDefinition
    for flow_type, priority, definition, examples in PRIORITY_DEFINITIONS:
        if not db.query(SlaPriorityDefinition).filter_by(flow_type=flow_type, priority=priority).first():
            db.add(SlaPriorityDefinition(flow_type=flow_type, priority=priority, definition=definition, examples=examples))
    for d in PROCESS_DEFS:
        if not db.query(ProcessDefinition).filter_by(code=d["code"]).first():
            definition = ProcessDefinition(
                code=d["code"], name=d["name"], entity_type=d["entity_type"], trigger_condition=d["trigger"]
            )
            db.add(definition)
            db.flush()
            for seq, step in enumerate(d["steps"], start=1):
                name, role, level, sla_hours = step[:4]
                cc = list(step[4]) if len(step) > 4 else []
                desc = step[5] if len(step) > 5 else None
                db.add(ProcessStep(definition_id=definition.id, seq=seq, name=name, default_role=role,
                                   cc_roles=cc, autonomy_level=level, sla_hours=sla_hours, description=desc))
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
