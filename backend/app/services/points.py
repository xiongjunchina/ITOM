"""积分服务（M6）：统一台账写入 + 自动事件订阅。

- award(): 唯一写入口（专项活动发放/自动事件/手工调整都走这里）
- 自动事件：订阅领域事件总线，按 point_rule 配置分值计分（规则停用即不计）
- period: 季度考核制（2026-07-12 定稿）——Q1/Q2/Q3 单季考核；Q4 不单独考核，
  10-12 月进入全年考核期 YYYY-All，全年统计覆盖本年度全部积分（Q1/Q2/Q3/All 打标）
"""
import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models import AuthUser, OrgMember, PointEntry, PointRule

logger = logging.getLogger("aom.points")


def current_period(d: date | None = None) -> str:
    """考核期序列：YYYY-Q1 / YYYY-Q2 / YYYY-Q3 / YYYY-All（Q4 并入全年考核）。"""
    d = d or date.today()
    quarter = (d.month - 1) // 3 + 1
    return f"{d.year}-All" if quarter == 4 else f"{d.year}-Q{quarter}"


def period_clause(col, period: str):
    """积分台账的考核期过滤：全年考核（YYYY-All）聚合本年度全部周期打标。"""
    if period.endswith("-All"):
        return col.like(f"{period.split('-')[0]}-%")
    return col == period


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
    contribution_bucket: str = "team_contribution",
    contribution_dimension: str | None = None,
) -> PointEntry:
    entry = PointEntry(
        person_id=person_id, points=points, source_type=source_type, source_ref=source_ref,
        campaign_id=campaign_id, task_id=task_id, period=period or current_period(),
        contribution_bucket=contribution_bucket, contribution_dimension=contribution_dimension,
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
    award(
        db, person_id, rule.points, rule_code, source_ref=source_ref, note=note or rule.name,
        contribution_bucket=rule.contribution_bucket or "team_contribution",
        contribution_dimension=rule.contribution_dimension,
    )


def award_by_rule_once(db: Session, rule_code: str, person_id: str | None, source_ref: str | None, note: str | None = None):
    """幂等自动积分：同一规则和来源单据只能产生一条有效流水。"""
    if not person_id or not source_ref:
        return
    # 领域事件可能在同一事务内连续投递；先 flush 让本事务已新增的流水
    # 参与查询，避免同一 session 内重复生成。
    db.flush()
    exists = db.query(PointEntry.id).filter(
        PointEntry.source_type == rule_code,
        PointEntry.source_ref == source_ref,
        PointEntry.is_deleted.is_(False),
    ).first()
    if exists:
        return
    award_by_rule(db, rule_code, person_id, source_ref, note)


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
    from app.models import BugFixTask, KnowledgeArticle, Milestone, Requirement, RequirementTask, Ticket, WbsTask, WorkTask

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

    @subscribe("bug_fix_task.completed")
    def _on_bug_fix_task_completed(db: Session, event_type, entity_type, entity_id, payload):
        task = db.get(BugFixTask, payload.get("task_id", entity_id))
        if not task or task.is_deleted or task.status != "关闭":
            return
        award_by_rule_once(db, "bug_fix_task_done", task.assignee, task.id, f"Bug 修复任务完成 {task.name[:30]}")

    @subscribe("work_task.closed")
    def _on_work_task_closed(db: Session, event_type, entity_type, entity_id, payload):
        task = db.get(WorkTask, entity_id)
        if not task or task.is_deleted or task.status != "关闭" or not task.assignee:
            return
        if task.performance_bucket == "team_contribution":
            from app.services.task_management import TEAM_CONTRIBUTION_TASK_RULES

            rule_code = TEAM_CONTRIBUTION_TASK_RULES.get(task.task_type)
            if rule_code:
                award_by_rule_once(db, rule_code, task.assignee, task.id, f"团队贡献任务完成 {task.title[:30]}")
        else:
            award_by_rule_once(db, "delegated_work_done", task.assignee, task.id, f"委派任务完成 {task.title[:30]}")

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
