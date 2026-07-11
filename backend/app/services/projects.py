"""项目域派生计算（PRD §6）：进度/健康度/SPI/CPI/成本全部实时计算，零录入。"""
from datetime import date

from sqlalchemy.orm import Session

from app.models import CostEntry, Milestone, Project, Risk, WbsTask

STATUS_PROGRESS = {"未开始": 0.0, "进行中": 0.5, "已完成": 1.0}


def task_weight(t: WbsTask) -> int:
    return max((t.end_date - t.start_date).days + 1, 1)


def compute_progress(tasks: list[WbsTask]) -> float | None:
    """进度 = 任务完成度按工期加权（PRD：状态映射 0/50/100）。"""
    if not tasks:
        return None
    total = sum(task_weight(t) for t in tasks)
    earned = sum(task_weight(t) * STATUS_PROGRESS.get(t.status, 0) for t in tasks)
    return round(earned / total * 100, 1)


def compute_planned_progress(tasks: list[WbsTask], today: date | None = None) -> float | None:
    """计划进度：按日期应完成的加权比例（SPI 分母）。"""
    if not tasks:
        return None
    today = today or date.today()
    total = 0
    planned = 0.0
    for t in tasks:
        w = task_weight(t)
        total += w
        if today >= t.end_date:
            ratio = 1.0
        elif today < t.start_date:
            ratio = 0.0
        else:
            ratio = ((today - t.start_date).days + 1) / task_weight(t)
        planned += w * ratio
    return round(planned / total * 100, 1) if total else None


def compute_metrics(db: Session, project: Project) -> dict:
    """一次算清项目详情/列表所需全部派生指标。"""
    tasks = db.query(WbsTask).filter(WbsTask.project_id == project.id, WbsTask.is_deleted.is_(False)).all()
    milestones = db.query(Milestone).filter(Milestone.project_id == project.id, Milestone.is_deleted.is_(False)).all()
    risks = db.query(Risk).filter(Risk.project_id == project.id, Risk.is_deleted.is_(False)).all()
    actual_cost = sum(
        c.amount_10k for c in db.query(CostEntry).filter(CostEntry.project_id == project.id, CostEntry.is_deleted.is_(False))
    )

    progress = compute_progress(tasks)
    planned = compute_planned_progress(tasks)
    spi = round(progress / planned, 2) if progress is not None and planned else None
    deviation = round(planned - progress, 1) if progress is not None and planned is not None else None

    today = date.today()
    overdue_milestones = [m for m in milestones if not m.achieved_at and m.target_date < today]
    red_risks = [r for r in risks if r.status == "开放" and r.probability == "高" and r.impact == "高"]

    # 健康度规则（PRD §6.1）：偏差>30% 或红色风险→红；偏差>15% 或里程碑逾期→黄
    health = "green"
    if project.status in ("active", "paused"):
        if (deviation is not None and deviation > 30) or red_risks:
            health = "red"
        elif (deviation is not None and deviation > 15) or overdue_milestones:
            health = "yellow"

    budget_usage = round(actual_cost / project.budget_10k * 100, 1) if project.budget_10k else None
    ev_value = (progress or 0) / 100 * project.budget_10k if project.budget_10k else None
    cpi = round(ev_value / actual_cost, 2) if ev_value is not None and actual_cost else None

    return {
        "progress": progress,
        "planned_progress": planned,
        "spi": spi,
        "cpi": cpi,
        "deviation": deviation,
        "health": health,
        "actual_cost_10k": round(actual_cost, 2),
        "budget_usage": budget_usage,
        "task_total": len(tasks),
        "task_done": sum(1 for t in tasks if t.status == "已完成"),
        "milestone_total": len(milestones),
        "milestone_overdue": len(overdue_milestones),
        "open_risks": sum(1 for r in risks if r.status == "开放"),
        "red_risks": len(red_risks),
    }


def rebuild_wbs_codes(db: Session, project_id: str):
    """按树位置重排 wbs_code（1、1.1、1.2、2…）。"""
    tasks = (
        db.query(WbsTask)
        .filter(WbsTask.project_id == project_id, WbsTask.is_deleted.is_(False))
        .order_by(WbsTask.sort, WbsTask.created_at)
        .all()
    )
    children: dict[str | None, list[WbsTask]] = {}
    for t in tasks:
        children.setdefault(t.parent_task_id, []).append(t)

    def walk(parent_id: str | None, prefix: str):
        for idx, t in enumerate(children.get(parent_id, []), start=1):
            t.wbs_code = f"{prefix}{idx}"
            walk(t.id, f"{t.wbs_code}.")

    walk(None, "")
