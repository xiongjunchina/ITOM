"""需求驳回/退回的领域投影与历史修复。"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import AuthUser, BusinessDomain, ProcessInstance, Requirement, RequirementScore
from app.services import process_engine
from app.services.audit import audit


_STATUS_BY_TARGET = {
    0: "supplementing",
    1: "evaluating",
    2: "analyzing",
    3: "implementing",
    4: "implementing",
}
_SCORE_FIELDS = (
    "score_d1_strategy",
    "score_d2_value",
    "score_d3_tech",
    "score_d4_org",
    "score_d5_risk",
    "score_d6_speed",
)


def invalidate_evaluation(db: Session, requirement: Requirement) -> None:
    """退回登记/需求评审时撤销当前共识，但保留评分行作为历史。"""
    for row in (
        db.query(RequirementScore)
        .filter(
            RequirementScore.requirement_id == requirement.id,
            RequirementScore.is_consensus.is_(True),
            RequirementScore.is_deleted.is_(False),
        )
        .all()
    ):
        row.is_consensus = False
    for field in _SCORE_FIELDS:
        setattr(requirement, field, None)
    requirement.decision = None


def project_return(
    db: Session,
    requirement: Requirement,
    target_seq: int,
    actor: AuthUser | None,
    reason: str,
    *,
    historical: bool = False,
) -> str:
    target_status = _STATUS_BY_TARGET.get(target_seq)
    if not target_status:
        raise AppError("INVALID_RETURN_TARGET", "退回节点无法映射需求阶段", 409)
    before = requirement.status
    requirement.status = target_status
    requirement.closed_at = None
    requirement.closure_note = None
    if target_seq <= 1:
        invalidate_evaluation(db, requirement)
    audit(db, "requirement", requirement.id, "historical_return_repair" if historical else "return", actor, {
        "from": before,
        "to": target_status,
        "target_seq": target_seq,
        "reason": reason,
    })
    return target_status


def resubmit(db: Session, requirement: Requirement, actor: AuthUser) -> ProcessInstance:
    instance = (
        db.query(ProcessInstance)
        .filter(
            ProcessInstance.entity_type == "requirement",
            ProcessInstance.entity_id == requirement.id,
            ProcessInstance.is_deleted.is_(False),
        )
        .order_by(ProcessInstance.created_at.desc())
        .with_for_update()
        .first()
    )
    if not instance or instance.status != "returned" or requirement.status != "supplementing":
        raise AppError("REQUIREMENT_NOT_RETURNED", "当前需求不在待登记人补充状态", 409)
    domain = db.get(BusinessDomain, requirement.business_domain_id)
    process_engine.resubmit_returned_requirement(db, instance, domain.owner_id if domain else None)
    requirement.status = "evaluating"
    if not requirement.evaluating_at:
        requirement.evaluating_at = datetime.now()
    audit(db, "requirement", requirement.id, "resubmit", actor, {"to": "evaluating"})
    return instance


def repair_rejected_instances(db: Session) -> int:
    """恢复旧版 generic reject 误终止的最新有效需求实例；可重复执行。"""
    instances = (
        db.query(ProcessInstance)
        .filter(
            ProcessInstance.entity_type == "requirement",
            ProcessInstance.status == "rejected",
            ProcessInstance.is_deleted.is_(False),
        )
        .order_by(ProcessInstance.created_at.asc())
        # Backend startup may overlap during a rolling deployment. Lock each
        # candidate so two replicas cannot both append a replacement task for
        # the same legacy instance.
        .with_for_update()
        .all()
    )
    repaired = 0
    for instance in instances:
        requirement = db.get(Requirement, instance.entity_id)
        if not requirement or requirement.is_deleted or requirement.status in ("closed", "cancelled", "on_hold"):
            continue
        latest_instance = (
            db.query(ProcessInstance.id)
            .filter(
                ProcessInstance.entity_type == "requirement",
                ProcessInstance.entity_id == instance.entity_id,
                ProcessInstance.is_deleted.is_(False),
            )
            .order_by(ProcessInstance.created_at.desc(), ProcessInstance.id.desc())
            .first()
        )
        # A requirement may have legacy/restarted process history. Never
        # resurrect an obsolete rejected instance behind the newest instance.
        if not latest_instance or latest_instance[0] != instance.id:
            continue
        target_seq = process_engine.restore_rejected_requirement_instance(db, instance)
        if target_seq is None:
            continue
        rejected_task = next(
            (
                task
                for task in sorted(instance.tasks, key=lambda item: item.created_at or datetime.min, reverse=True)
                if not task.is_deleted and task.status == "已驳回"
            ),
            None,
        )
        project_return(
            db,
            requirement,
            target_seq,
            None,
            rejected_task.comment if rejected_task and rejected_task.comment else "历史驳回流程恢复",
            historical=True,
        )
        repaired += 1
    return repaired
