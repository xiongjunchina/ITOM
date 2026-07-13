"""项目域派生计算（PRD §6）：进度/健康度/SPI/CPI/成本全部实时计算，零录入。"""
from datetime import date

from sqlalchemy.orm import Session

from app.models import CostEntry, Milestone, Project, Risk, WbsTask

STATUS_PROGRESS = {"未开始": 0.0, "进行中": 0.5, "已完成": 1.0}


def wbs_status(progress: int, end_date: date | None, today: date | None = None) -> str:
    """状态计算（与 WBS 模板公式一致）：完成100→已完成；未完且已过计划结束→已延期；完成0→未开始；否则进行中。"""
    today = today or date.today()
    if (progress or 0) >= 100:
        return "已完成"
    if end_date and today > end_date:
        return "已延期"
    if (progress or 0) <= 0:
        return "未开始"
    return "进行中"


def wbs_deviation(actual_end: date | None, end_date: date | None) -> int | None:
    """进度偏差(天) = 实际结束 − 计划结束（>0 延期，<0 提前）。"""
    if actual_end and end_date:
        return (actual_end - end_date).days
    return None


def task_weight(t: WbsTask) -> int:
    return max((t.end_date - t.start_date).days + 1, 1)


def _coerce_date(v) -> date | None:
    if not v:
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def create_wbs_by_code(db: Session, project: Project, rows: list[dict], *, default_assignee: str | None = None,
                       sort_base: int = 0) -> tuple[int, list[str]]:
    """按 WBS编号建 WBS：层级由编号前缀推导（1.1 的父级是 1），前置按编号引用；里程碑=WBS 标志。

    rows 键：stage/wbs_code/name/wbs_dict/deliverable/assignee_name/is_milestone/
             predecessor_codes(list|逗号串)/start_date/end_date/actual_start/actual_end/progress/remarks。
    返回 (创建数, 错误消息列表)。负责人姓名未匹配时用 default_assignee（章程默认 PM）。
    """
    from datetime import datetime

    from app.models import OrgMember, WbsTask

    members = {m.name: m.id for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False), OrgMember.status == "在岗")}
    errors: list[str] = []
    by_code: dict[str, WbsTask] = {}
    order: list[tuple[dict, WbsTask]] = []
    for r in rows:
        name = (r.get("name") or "").strip()
        if not name:
            continue
        code = str(r.get("wbs_code") or "").strip() or str(sort_base + len(order) + 1)
        if code in by_code:
            errors.append(f"WBS编号「{code}」重复，已跳过")
            continue
        assignee = members.get((r.get("assignee_name") or "").strip()) or default_assignee
        if not assignee:
            errors.append(f"任务「{name}」的责任人「{r.get('assignee_name') or ''}」不是在岗人员")
            continue
        start, end = _coerce_date(r.get("start_date")), _coerce_date(r.get("end_date"))
        if not start or not end:
            errors.append(f"任务「{name}」缺计划开始/结束日期")
            continue
        if end < start:
            start = end
        ms = r.get("is_milestone")
        ms = ms if isinstance(ms, bool) else (str(ms).strip() in ("是", "Y", "y", "yes", "true", "1"))
        try:
            prog = int(r.get("progress") or 0)
        except (TypeError, ValueError):
            prog = 0
        prog = prog if prog in (0, 50, 100) else 0
        task = WbsTask(
            project_id=project.id, wbs_code=code, stage=r.get("stage"), name=name,
            wbs_dict=r.get("wbs_dict"), deliverable=r.get("deliverable"), assignee=assignee, is_milestone=ms,
            start_date=start, end_date=end,
            actual_start=_coerce_date(r.get("actual_start")), actual_end=_coerce_date(r.get("actual_end")),
            progress=prog, remarks=r.get("remarks"), sort=sort_base + len(order),
        )
        if prog >= 100:
            task.completed_at = datetime.now()
        db.add(task)
        db.flush()
        by_code[code] = task
        order.append((r, task))
    for r, task in order:  # 第二遍：父级由编号前缀、前置按编号
        if "." in task.wbs_code:
            parent = by_code.get(task.wbs_code.rsplit(".", 1)[0])
            if parent and parent.id != task.id:
                task.parent_task_id = parent.id
        preds = r.get("predecessor_codes")
        if isinstance(preds, str):
            preds = [x.strip() for x in preds.replace("，", ",").split(",") if x.strip()]
        pred_ids = [by_code[str(pc).strip()].id for pc in (preds or [])
                    if str(pc).strip() in by_code and by_code[str(pc).strip()].id != task.id]
        if pred_ids:
            task.predecessor_ids = pred_ids
    return len(order), errors


def compute_progress(tasks: list[WbsTask]) -> float | None:
    """进度 = 任务完成度按工期加权（PRD：状态映射 0/50/100）。"""
    if not tasks:
        return None
    total = sum(task_weight(t) for t in tasks)
    earned = sum(task_weight(t) * ((t.progress or 0) / 100) for t in tasks)  # 完成度% 三档 0/50/100
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
    milestone_tasks = [t for t in tasks if t.is_milestone]  # 里程碑=WBS 勾选「是」的行（派生）
    risks = db.query(Risk).filter(Risk.project_id == project.id, Risk.is_deleted.is_(False)).all()
    actual_cost = sum(
        c.amount_10k for c in db.query(CostEntry).filter(CostEntry.project_id == project.id, CostEntry.is_deleted.is_(False))
    )

    progress = compute_progress(tasks)
    planned = compute_planned_progress(tasks)
    spi = round(progress / planned, 2) if progress is not None and planned else None
    deviation = round(planned - progress, 1) if progress is not None and planned is not None else None

    today = date.today()
    overdue_milestones = [t for t in milestone_tasks if wbs_status(t.progress, t.end_date, today) == "已延期"]
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
        "task_done": sum(1 for t in tasks if (t.progress or 0) >= 100),
        "milestone_total": len(milestone_tasks),
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
