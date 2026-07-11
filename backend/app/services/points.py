"""积分服务（M6）：统一台账写入 + 自动事件订阅。

- award(): 唯一写入口（专项活动发放/自动事件/手工调整都走这里）
- 自动事件：订阅领域事件总线，按 point_rule 配置分值计分（规则停用即不计）
- period: 未显式指定时按自然半年归期（2026-H1/H2），与专项活动的考核期同一维度
"""
import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models import AuthUser, OrgMember, PointEntry, PointRule

logger = logging.getLogger("aom.points")


def current_period(d: date | None = None) -> str:
    d = d or date.today()
    return f"{d.year}-H{1 if d.month <= 6 else 2}"


def award(
    db: Session,
    person_id: str,
    points: float,
    source_type: str,
    source_ref: str | None = None,
    campaign_id: str | None = None,
    task_id: str | None = None,
    period: str | None = None,
    note: str | None = None,
    created_by: str | None = None,
) -> PointEntry:
    entry = PointEntry(
        person_id=person_id, points=points, source_type=source_type, source_ref=source_ref,
        campaign_id=campaign_id, task_id=task_id, period=period or current_period(),
        note=note, created_by=created_by,
    )
    db.add(entry)
    return entry


def award_by_rule(db: Session, rule_code: str, person_id: str | None, source_ref: str | None, note: str | None = None):
    """按规则计分：规则不存在/停用/无人员时静默跳过（自动事件容错）。"""
    if not person_id:
        return
    rule = db.query(PointRule).filter(PointRule.code == rule_code, PointRule.active.is_(True), PointRule.is_deleted.is_(False)).first()
    if not rule or not rule.points:
        return
    if not db.get(OrgMember, person_id):
        return
    award(db, person_id, rule.points, rule_code, source_ref=source_ref, note=note or rule.name)


def _person_of_user(db: Session, user_id: str | None) -> str | None:
    if not user_id:
        return None
    user = db.get(AuthUser, user_id)
    return user.person_id if user else None


# ---------- 自动事件订阅（挂事件总线） ----------

_REGISTERED = False


def register_subscribers():
    """幂等：进程内只挂接一次（测试多次启动 lifespan / 多 worker 场景）。"""
    global _REGISTERED
    if _REGISTERED:
        return
    _REGISTERED = True
    from app.events.bus import subscribe
    from app.models import KnowledgeArticle, Milestone, Requirement, RequirementTask, Ticket, WbsTask

    @subscribe("ticket.resolved")
    def _on_ticket_resolved(db: Session, event_type, entity_type, entity_id, payload):
        t = db.get(Ticket, entity_id)
        if not t or t.is_example or not t.assignee:
            return
        award_by_rule(db, "ticket_resolved", t.assignee, t.id, f"工单解决 {t.ticket_code}")

    @subscribe("ticket.closed")
    def _on_ticket_closed(db: Session, event_type, entity_type, entity_id, payload):
        t = db.get(Ticket, entity_id)
        if not t or t.is_example or not t.assignee:
            return
        if t.sla_response_met and t.sla_resolution_met:
            award_by_rule(db, "ticket_sla_met", t.assignee, t.id, f"SLA 双达成 {t.ticket_code}")

    @subscribe("ticket.satisfaction_rated")
    def _on_satisfaction(db: Session, event_type, entity_type, entity_id, payload):
        t = db.get(Ticket, entity_id)
        if not t or t.is_example or not t.assignee:
            return
        award_by_rule(db, "ticket_satisfaction", t.assignee, t.id, f"满意度好评 {t.ticket_code}")

    @subscribe("wbs.completed")
    def _on_wbs_done(db: Session, event_type, entity_type, entity_id, payload):
        task = db.get(WbsTask, payload.get("task_id", ""))
        if not task or task.is_example or not payload.get("on_time"):
            return
        award_by_rule(db, "wbs_done_on_time", task.assignee, task.id, f"任务按期完成 {task.name[:30]}")

    @subscribe("milestone.achieved")
    def _on_milestone(db: Session, event_type, entity_type, entity_id, payload):
        m = db.get(Milestone, payload.get("milestone_id", ""))
        if not m or m.is_example:
            return
        from app.models import Project

        project = db.get(Project, m.project_id)
        if project and not project.is_example:
            award_by_rule(db, "milestone_achieved", project.pm, m.id, f"里程碑达成 {m.name[:30]}")

    @subscribe("requirement.task_completed")
    def _on_req_task(db: Session, event_type, entity_type, entity_id, payload):
        task = db.get(RequirementTask, payload.get("task_id", ""))
        if not task or task.is_example:
            return
        award_by_rule(db, "requirement_task_done", task.assignee, task.id, f"需求任务完成 {task.name[:30]}")

    @subscribe("requirement.closed")
    def _on_req_closed(db: Session, event_type, entity_type, entity_id, payload):
        r = db.get(Requirement, entity_id)
        if not r or r.is_example or not r.owner:
            return
        award_by_rule(db, "requirement_closed", r.owner, r.id, f"需求交付 {r.requirement_code}")

    @subscribe("knowledge.published")
    def _on_kb_published(db: Session, event_type, entity_type, entity_id, payload):
        a = db.get(KnowledgeArticle, entity_id)
        if not a or a.is_example:
            return
        award_by_rule(db, "knowledge_published", _person_of_user(db, a.author), a.id, f"发表知识 {a.title[:30]}")

    @subscribe("knowledge.voted")
    def _on_kb_voted(db: Session, event_type, entity_type, entity_id, payload):
        a = db.get(KnowledgeArticle, entity_id)
        if not a or a.is_example:
            return
        award_by_rule(db, "knowledge_voted", _person_of_user(db, a.author), a.id, f"知识被点有用 {a.title[:30]}")

    logger.info("points subscribers registered")
