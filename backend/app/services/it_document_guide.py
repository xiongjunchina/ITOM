"""IT 员工单据速查与无状态分流规则。

本模块只提供可解释的静态帮助内容和推荐结果，不持久化问答，
也不替代目标单据的权限、字段或流程校验。
"""
from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.core.i18n import get_lang
from app.models import AuthUser
from app.services.permissions import TICKET_TYPE_MODULE, has_perm
from app.services.team_scope import is_it_member


GUIDE_VERSION = "2026-07-31"


DOCUMENTS: tuple[dict, ...] = (
    {
        "type": "service_request",
        "module": "ticket_sr",
        "target_path": "/itsm/tickets?create=1",
        "label": {"zh": "服务请求", "en": "Service Request"},
        "suitable": {"zh": "单个用户对既有 IT 能力的故障、协助、访问、安装、配置或咨询。", "en": "A single user's issue, assistance, access, installation, configuration, or consultation for an existing IT capability."},
        "positive_example": {"zh": "例如：员工无法连接公司 Wi-Fi，需要协助排查。", "en": "Example: an employee cannot connect to company Wi-Fi and needs troubleshooting help."},
        "not_suitable": {"zh": "不用于大范围中断或新系统、新功能想法。", "en": "Do not use for broad outages or ideas for new systems or features."},
        "redirect": {"zh": "大范围中断转事件；新能力想法转 IT 需求。", "en": "Use Incident for broad outages; use IT Requirement for new capability ideas."},
    },
    {
        "type": "incident",
        "module": "ticket_incident",
        "target_path": "/itsm/incidents?create=1",
        "label": {"zh": "事件", "en": "Incident"},
        "suitable": {"zh": "网络、服务器、应用等影响多名用户、一个服务或核心系统的中断。", "en": "An outage affecting multiple users, a service, or a core network, server, or application."},
        "positive_example": {"zh": "例如：办公网络中断，多个部门无法访问业务系统。", "en": "Example: an office network outage prevents multiple departments from accessing business systems."},
        "not_suitable": {"zh": "不用于单个用户的软件打不开等个体报障。", "en": "Do not use for an individual user's single-device or software issue."},
        "redirect": {"zh": "单人既有能力故障转服务请求；反复故障转问题。", "en": "Use Service Request for an individual issue; use Problem for recurring failures."},
    },
    {
        "type": "problem",
        "module": "problems",
        "target_path": "/itsm/problems?create=1",
        "label": {"zh": "问题", "en": "Problem"},
        "suitable": {"zh": "已知错误、反复发生的故障，或需要定位根因的事项。", "en": "A known error, recurring failure, or issue that requires root-cause analysis."},
        "positive_example": {"zh": "例如：同一应用每月反复发生连接池耗尽，需要根因分析。", "en": "Example: an application repeatedly exhausts its connection pool and needs root-cause analysis."},
        "not_suitable": {"zh": "不用于一次性的个人服务请求本身。", "en": "Do not use for a one-off individual service request itself."},
        "redirect": {"zh": "单次个人报障转服务请求；需要生产修改时再建立变更。", "en": "Use Service Request for a one-off report; create a Change when production modification is required."},
    },
    {
        "type": "change",
        "module": "ticket_change",
        "target_path": "/itsm/changes?create=1",
        "label": {"zh": "变更", "en": "Change"},
        "suitable": {"zh": "有计划的生产环境修改，需管理风险、回退方案和实施窗口。", "en": "A planned production modification requiring risk, rollback, and implementation-window control."},
        "positive_example": {"zh": "例如：计划在周末调整生产网络访问策略并准备回退方案。", "en": "Example: changing a production network access policy over the weekend with a rollback plan."},
        "not_suitable": {"zh": "不用于普通故障处理或新功能想法本身。", "en": "Do not use for ordinary incident handling or a new-feature idea itself."},
        "redirect": {"zh": "故障影响先登记事件/问题；新功能先登记 IT 需求。", "en": "Record an Incident or Problem first for failures; record an IT Requirement first for a new feature."},
    },
    {
        "type": "requirement",
        "module": "requirements",
        "target_path": "/requirements/overview?create=1",
        "label": {"zh": "IT 需求", "en": "IT Requirement"},
        "suitable": {"zh": "新系统、新功能、优化或重构等需要评估的想法。", "en": "An idea for a new system, function, optimisation, or refactoring that requires assessment."},
        "positive_example": {"zh": "例如：希望增加供应链系统的移动审批功能。", "en": "Example: requesting mobile approvals for the supply-chain system."},
        "not_suitable": {"zh": "不直接替代受控生产变更。", "en": "Do not use as a substitute for a controlled production change."},
        "redirect": {"zh": "经评估达到项目门槛时再转项目；生产实施另建变更。", "en": "Convert to a Project after assessment when the project threshold is met; create a Change for production implementation."},
    },
    {
        "type": "project",
        "module": "projects",
        "target_path": "/projects/list?create=1",
        "label": {"zh": "项目", "en": "Project"},
        "suitable": {"zh": "需要章程、WBS、里程碑、资源、成本或风险管理的交付，通常达到项目人力门槛。", "en": "A delivery requiring a charter, WBS, milestones, resource, cost, or risk management, typically meeting the project effort threshold."},
        "positive_example": {"zh": "例如：跨部门上线新 ERP 模块并进行多阶段交付管理。", "en": "Example: delivering a new ERP module across departments in multiple managed phases."},
        "not_suitable": {"zh": "不用于普通临时任务或尚未评估的想法。", "en": "Do not use for an ordinary temporary task or an unevaluated idea."},
        "redirect": {"zh": "临时工作转委派任务；新想法先登记 IT 需求。", "en": "Use Delegated Task for temporary work; record an IT Requirement first for a new idea."},
    },
)


def _localized(value: dict[str, str]) -> str:
    return value.get(get_lang(), value["zh"])


def _document(item: dict, can_create: bool) -> dict:
    return {
        "type": item["type"],
        "label": _localized(item["label"]),
        "suitable": _localized(item["suitable"]),
        "positive_example": _localized(item["positive_example"]),
        "not_suitable": _localized(item["not_suitable"]),
        "redirect": _localized(item["redirect"]),
        "target_path": item["target_path"] if can_create else None,
        "can_create": can_create,
    }


def available_types(db: Session, user: AuthUser) -> set[str]:
    return {item["type"] for item in DOCUMENTS if has_perm(db, user, item["module"], "create")}


def staff_intake_enabled(db: Session, user: AuthUser, available: Iterable[str] | None = None) -> bool:
    return is_it_member(db, user.person_id) and bool(set(available if available is not None else available_types(db, user)))


def guide_payload(db: Session, user: AuthUser) -> dict:
    available = available_types(db, user)
    return {
        "version": GUIDE_VERSION,
        "staff_intake": {
            "enabled": staff_intake_enabled(db, user, available),
            "available_types": [item["type"] for item in DOCUMENTS if item["type"] in available],
        },
        "documents": [_document(item, item["type"] in available) for item in DOCUMENTS],
    }


def recommend(*, broad_impact: bool, recurring_or_root_cause: bool, planned_production_change: bool, new_capability: bool) -> dict:
    if broad_impact:
        selected = "incident"
        reason = {"zh": "影响多个用户、服务或核心系统，应优先按事件协调恢复。", "en": "The impact reaches multiple users, a service, or a core system, so coordinate restoration as an Incident."}
        counterexample = {"zh": "单个用户无法使用既有软件通常应登记服务请求。", "en": "An individual user unable to use existing software is normally a Service Request."}
    elif recurring_or_root_cause:
        selected = "problem"
        reason = {"zh": "这是反复发生或需要根因分析的事项，应纳入问题管理。", "en": "This is recurring or requires root-cause analysis, so it belongs in Problem Management."}
        counterexample = {"zh": "一次性的个人故障通常应登记服务请求。", "en": "A one-off personal issue is normally a Service Request."}
    elif planned_production_change:
        selected = "change"
        reason = {"zh": "生产环境计划修改需要风险、回退和窗口控制，应登记变更。", "en": "A planned production modification needs risk, rollback, and window controls, so it is a Change."}
        counterexample = {"zh": "新功能想法应先登记 IT 需求，而不是直接创建变更。", "en": "A new-feature idea should first be an IT Requirement, not a direct Change."}
    elif new_capability:
        selected = "requirement"
        reason = {"zh": "这是新系统、功能、优化或重构想法，需要先进入 IT 需求评估。", "en": "This is a new system, function, optimisation, or refactoring idea and should first enter IT Requirement assessment."}
        counterexample = {"zh": "临时执行性工作应登记为委派任务，不必创建 IT 需求。", "en": "A temporary execution task should be a Delegated Task rather than an IT Requirement."}
    else:
        selected = "service_request"
        reason = {"zh": "这是对既有 IT 能力的个人故障、协助或申请，应登记服务请求。", "en": "This is an individual issue, assistance request, or application for an existing IT capability, so it is a Service Request."}
        counterexample = {"zh": "影响多个用户或核心系统时应升级为事件。", "en": "When multiple users or a core system are affected, use an Incident."}

    item = next(item for item in DOCUMENTS if item["type"] == selected)
    return {
        "recommended_type": selected,
        "recommended_label": _localized(item["label"]),
        "reason": _localized(reason),
        "counterexample": _localized(counterexample),
        "target_path": item["target_path"],
    }


def ticket_module_for_document(document_type: str) -> str | None:
    """保留单据类型与现有权限矩阵的显式映射，供后续关联服务复用。"""
    if document_type in TICKET_TYPE_MODULE:
        return TICKET_TYPE_MODULE[document_type]
    item = next((item for item in DOCUMENTS if item["type"] == document_type), None)
    return item["module"] if item else None
