"""人效评分引擎（M6.1）：按岗位匹配计分方案，维度得分×权重加权。

设计（用户口径 2026-07-12）：
- 绩效分 ≠ 贡献积分。积分只是其中一个维度（activity_points）。
- 方案（perf_scheme）绑定岗位：不同岗位类型各自定义「维度 + 权重」，全部可自定义。
- 维度库固定在代码里（每个维度一个计算器，产出 0-100 标准化分或 None=无数据）；
  维度口径为 v1 默认实现，正式口径确认后在此调整，页面展示口径说明。
- 无数据维度不参与计分（权重自动归一化）；公共维度（知识/积分）无贡献计 0 分。
- 权重不强制合计 100：计算按占比归一，页面提示合计。
"""
from datetime import date, datetime, time

from sqlalchemy.orm import Session

from app.models import (
    AuthUser,
    PerfAdjustment,
    PerfOverride,
    BusinessDomain,
    BusinessDomainMember,
    KnowledgeArticle,
    KnowledgeVote,
    OrgMember,
    PerfScheme,
    PointEntry,
    RequirementTask,
    Ticket,
    WbsTask,
)

# (code, name, 公共维度=无数据计0, 口径说明)
DIMENSIONS = [
    ("ticket_service", "服务工单", False,
     "考核期内经办并解决的服务请求/事件工单：SLA 解决达成率 ×60% + 满意度均分（百分制）×40%；"
     "期内无满意度评价时按 SLA 达成率全额计。期内无经办工单 → 该维度不计入（权重自动归一）。"),
    ("change_compliance", "运维合规（变更）", False,
     "考核期内经办且已完结的变更单中，经审批后正常关闭的占比；被拒绝/回退/未审批即关闭视为不合规。"
     "期内无变更单 → 不计入。"),
    ("project_delivery", "项目交付", False,
     "考核期内计划到期的 WBS 任务按期完成率（完成时间 ≤ 计划结束日；到期未完成计不按期）。"
     "未到期任务不参与。期内无到期任务 → 不计入。"),
    ("requirement_delivery", "需求交付", False,
     "考核期内计划到期的需求任务按期完成率（口径同项目交付）。期内无到期任务 → 不计入。"),
    ("domain_satisfaction", "业务域满意度", False,
     "本人所在业务域全体成员经办工单的满意度均分（百分制）——服务线共担指标。"
     "未加入业务域或域内期内无评价 → 不计入。"),
    ("knowledge_contrib", "知识贡献", True,
     "考核期内发布知识 ×20 分 + 文章被点有用 ×5 分，封顶 100。公共指标：无贡献计 0 分。"),
    ("activity_points", "活动积分", True,
     "考核期内积分台账合计（自动积分 + 专项活动积分）÷ 团队最高值 ×100（相对分）。"
     "公共指标：无积分计 0 分。"),
]
DIMENSION_CODES = {d[0] for d in DIMENSIONS}
PUBLIC_DIMENSIONS = {d[0] for d in DIMENSIONS if d[2]}


def period_range(period: str) -> tuple[datetime, datetime]:
    """考核期 → 统计时间范围：Q1-Q3 单季；YYYY-All 全年考核=本年度全范围。"""
    year, _, tag = period.partition("-")
    y = int(year)
    if tag == "Q1":
        return datetime(y, 1, 1), datetime.combine(date(y, 3, 31), time.max)
    if tag == "Q2":
        return datetime(y, 4, 1), datetime.combine(date(y, 6, 30), time.max)
    if tag == "Q3":
        return datetime(y, 7, 1), datetime.combine(date(y, 9, 30), time.max)
    return datetime(y, 1, 1), datetime.combine(date(y, 12, 31), time.max)  # YYYY-All 全年


def _rate(hits: int, total: int) -> float | None:
    return round(hits / total * 100, 1) if total else None


def _score_ticket_service(db: Session, member_ids: list[str], start, end) -> dict[str, float]:
    rows = (
        db.query(Ticket)
        .filter(
            Ticket.assignee.in_(member_ids), Ticket.is_deleted.is_(False), Ticket.is_example.is_(False),
            Ticket.ticket_type.in_(["service_request", "incident"]),
            Ticket.resolved_at.isnot(None), Ticket.resolved_at >= start, Ticket.resolved_at <= end,
        )
        .all()
    )
    per: dict[str, dict] = {}
    for t in rows:
        d = per.setdefault(t.assignee, {"n": 0, "sla_ok": 0, "sla_n": 0, "sat": [], })
        d["n"] += 1
        if t.sla_resolution_met is not None:
            d["sla_n"] += 1
            d["sla_ok"] += 1 if t.sla_resolution_met else 0
        if t.satisfaction:
            d["sat"].append(t.satisfaction * 20)
    out = {}
    for pid, d in per.items():
        sla = _rate(d["sla_ok"], d["sla_n"])
        sat = round(sum(d["sat"]) / len(d["sat"]), 1) if d["sat"] else None
        if sla is None and sat is None:
            continue
        if sat is None:
            out[pid] = sla
        elif sla is None:
            out[pid] = sat
        else:
            out[pid] = round(sla * 0.6 + sat * 0.4, 1)
    return out


def _score_change_compliance(db: Session, member_ids: list[str], start, end) -> dict[str, float]:
    rows = (
        db.query(Ticket)
        .filter(
            Ticket.assignee.in_(member_ids), Ticket.is_deleted.is_(False), Ticket.is_example.is_(False),
            Ticket.ticket_type == "change",
            Ticket.status.in_(["closed", "rejected", "rolled_back"]),
            Ticket.updated_at >= start, Ticket.updated_at <= end,
        )
        .all()
    )
    per: dict[str, dict] = {}
    for t in rows:
        d = per.setdefault(t.assignee, {"ok": 0, "n": 0})
        d["n"] += 1
        if t.status == "closed" and t.approved_at is not None and t.closure_code != "cancelled":
            d["ok"] += 1
    return {pid: _rate(d["ok"], d["n"]) for pid, d in per.items() if d["n"]}


def _score_project_delivery(db: Session, member_ids: list[str], start, end) -> dict[str, float]:
    today = date.today()
    rows = (
        db.query(WbsTask)
        .filter(
            WbsTask.assignee.in_(member_ids), WbsTask.is_deleted.is_(False), WbsTask.is_example.is_(False),
            WbsTask.end_date >= start.date(), WbsTask.end_date <= end.date(),
        )
        .all()
    )
    per: dict[str, dict] = {}
    for t in rows:
        done = (t.progress or 0) >= 100  # M9：WbsTask 以完成度替代 status
        if not done and t.end_date >= today:
            continue  # 未到期且未完成：不参与
        d = per.setdefault(t.assignee, {"ok": 0, "n": 0})
        d["n"] += 1
        if done and t.completed_at and t.completed_at.date() <= t.end_date:
            d["ok"] += 1
    return {pid: _rate(d["ok"], d["n"]) for pid, d in per.items() if d["n"]}


def _score_requirement_delivery(db: Session, member_ids: list[str], start, end) -> dict[str, float]:
    today = date.today()
    rows = (
        db.query(RequirementTask)
        .filter(
            RequirementTask.assignee.in_(member_ids), RequirementTask.is_deleted.is_(False),
            RequirementTask.is_example.is_(False),
            RequirementTask.plan_date.isnot(None),
            RequirementTask.plan_date >= start.date(), RequirementTask.plan_date <= end.date(),
        )
        .all()
    )
    per: dict[str, dict] = {}
    for t in rows:
        done = t.status == "已完成"
        if not done and t.plan_date >= today:
            continue
        d = per.setdefault(t.assignee, {"ok": 0, "n": 0})
        d["n"] += 1
        if done and t.done_at and t.done_at.date() <= t.plan_date:
            d["ok"] += 1
    return {pid: _rate(d["ok"], d["n"]) for pid, d in per.items() if d["n"]}


def _score_domain_satisfaction(db: Session, member_ids: list[str], start, end) -> dict[str, float]:
    # 成员 → 所在域（域成员表 ∪ 域负责人）
    domain_of: dict[str, str] = {}
    for dm in db.query(BusinessDomainMember).filter(BusinessDomainMember.is_deleted.is_(False)):
        domain_of.setdefault(dm.person_id, dm.domain_id)
    for dom in db.query(BusinessDomain).filter(BusinessDomain.is_deleted.is_(False)):
        if dom.owner_id:
            domain_of.setdefault(dom.owner_id, dom.id)

    members_of: dict[str, set[str]] = {}
    for pid, did in domain_of.items():
        members_of.setdefault(did, set()).add(pid)

    # 域满意度 = 域内全体成员经办工单的满意度均分
    domain_score: dict[str, float] = {}
    for did, pids in members_of.items():
        rows = (
            db.query(Ticket.satisfaction)
            .filter(
                Ticket.assignee.in_(list(pids)), Ticket.is_deleted.is_(False), Ticket.is_example.is_(False),
                Ticket.satisfaction.isnot(None),
                Ticket.resolved_at >= start, Ticket.resolved_at <= end,
            )
            .all()
        )
        if rows:
            domain_score[did] = round(sum(s for (s,) in rows) / len(rows) * 20, 1)
    return {pid: domain_score[did] for pid, did in domain_of.items() if did in domain_score and pid in set(member_ids)}


def _score_knowledge_contrib(db: Session, member_ids: list[str], start, end) -> dict[str, float]:
    user_person = {
        u.id: u.person_id
        for u in db.query(AuthUser).filter(AuthUser.person_id.isnot(None), AuthUser.is_deleted.is_(False))
        if u.person_id in set(member_ids)
    }
    per: dict[str, float] = {pid: 0.0 for pid in member_ids}  # 公共维度：默认 0
    articles = (
        db.query(KnowledgeArticle)
        .filter(
            KnowledgeArticle.is_deleted.is_(False), KnowledgeArticle.is_example.is_(False),
            KnowledgeArticle.status == "published", KnowledgeArticle.author.in_(list(user_person)),
        )
        .all()
    )
    article_owner = {}
    for a in articles:
        pid = user_person.get(a.author)
        if not pid:
            continue
        article_owner[a.id] = pid
        if start <= a.created_at <= end:
            per[pid] = per.get(pid, 0) + 20
    if article_owner:
        votes = (
            db.query(KnowledgeVote)
            .filter(
                KnowledgeVote.article_id.in_(list(article_owner)), KnowledgeVote.is_deleted.is_(False),
                KnowledgeVote.created_at >= start, KnowledgeVote.created_at <= end,
            )
            .all()
        )
        for v in votes:
            pid = article_owner[v.article_id]
            per[pid] = per.get(pid, 0) + 5
    return {pid: min(100.0, round(s, 1)) for pid, s in per.items()}


def _score_activity_points(db: Session, member_ids: list[str], period: str, **_) -> dict[str, float]:
    from sqlalchemy import func

    from app.services.points import period_clause

    rows = (
        db.query(PointEntry.person_id, func.sum(PointEntry.points))
        .filter(period_clause(PointEntry.period, period), PointEntry.is_deleted.is_(False),
                PointEntry.person_id.in_(member_ids))
        .group_by(PointEntry.person_id)
        .all()
    )
    totals = {pid: float(pts) for pid, pts in rows}
    top = max(totals.values(), default=0)
    per = {pid: 0.0 for pid in member_ids}
    if top > 0:
        for pid, pts in totals.items():
            per[pid] = round(pts / top * 100, 1)
    return per


def match_scheme(member: OrgMember, schemes: list[PerfScheme]) -> PerfScheme | None:
    """岗位精确匹配优先（按创建先后），否则默认方案。"""
    if member.position_id:
        for s in schemes:
            if member.position_id in (s.position_ids or []):
                return s
    return next((s for s in schemes if s.is_default), None)


def compute_performance(db: Session, period: str) -> dict:
    start, end = period_range(period)
    members = (
        db.query(OrgMember)
        .filter(OrgMember.is_deleted.is_(False), OrgMember.status == "在岗")
        .all()
    )
    member_ids = [m.id for m in members]
    schemes = (
        db.query(PerfScheme)
        .filter(PerfScheme.is_deleted.is_(False), PerfScheme.active.is_(True))
        .order_by(PerfScheme.created_at)
        .all()
    )

    scores: dict[str, dict[str, float]] = {}
    if member_ids:
        scores["ticket_service"] = _score_ticket_service(db, member_ids, start, end)
        scores["change_compliance"] = _score_change_compliance(db, member_ids, start, end)
        scores["project_delivery"] = _score_project_delivery(db, member_ids, start, end)
        scores["requirement_delivery"] = _score_requirement_delivery(db, member_ids, start, end)
        scores["domain_satisfaction"] = _score_domain_satisfaction(db, member_ids, start, end)
        scores["knowledge_contrib"] = _score_knowledge_contrib(db, member_ids, start, end)
        scores["activity_points"] = _score_activity_points(db, member_ids, period=period)

    # 核定分（系统值只是初始参考，管理岗可覆盖）与加减分事项
    overrides = {
        (o.person_id, o.dimension_code): o.score
        for o in db.query(PerfOverride).filter(PerfOverride.period == period, PerfOverride.is_deleted.is_(False))
    }
    adj_map: dict[str, list] = {}
    for a in (
        db.query(PerfAdjustment)
        .filter(PerfAdjustment.period == period, PerfAdjustment.is_deleted.is_(False))
        .order_by(PerfAdjustment.created_at)
    ):
        adj_map.setdefault(a.person_id, []).append(a)

    rows = []
    for m in members:
        scheme = match_scheme(m, schemes)
        adjs = adj_map.get(m.id, [])
        bonus = round(sum(a.points for a in adjs if a.kind == "bonus"), 1)
        penalty = round(sum(a.points for a in adjs if a.kind == "penalty"), 1)
        adj_rows = [
            {"id": a.id, "kind": a.kind, "points": a.points, "reason": a.reason, "created_at": a.created_at}
            for a in adjs
        ]
        base = {
            "person_id": m.id, "person_name": m.name, "position_name": m.position.name if m.position else None,
            "bonus": bonus, "penalty": penalty, "adjustments": adj_rows,
        }
        if not scheme:
            total = round(bonus - penalty, 1) if adjs else None
            rows.append({**base, "scheme_id": None, "scheme_name": None,
                         "base_score": None, "total": total, "dims": {}})
            continue
        dims = {}
        weighted_sum = 0.0
        weight_sum = 0.0
        for item in scheme.dimensions or []:
            code, weight = item.get("code"), float(item.get("weight") or 0)
            if code not in DIMENSION_CODES or weight <= 0:
                continue
            score = scores.get(code, {}).get(m.id)
            if score is None and code in PUBLIC_DIMENSIONS:
                score = 0.0
            override = overrides.get((m.id, code))
            effective = override if override is not None else score
            dims[code] = {"score": score, "override": override, "effective": effective, "weight": weight}
            if effective is not None:
                weighted_sum += effective * weight
                weight_sum += weight
        base_score = round(weighted_sum / weight_sum, 1) if weight_sum else None
        total = None
        if base_score is not None or adjs:
            total = round((base_score or 0) + bonus - penalty, 1)
        rows.append({**base, "scheme_id": scheme.id, "scheme_name": scheme.name,
                     "base_score": base_score, "total": total, "dims": dims})
    rows.sort(key=lambda r: (r["total"] is None, -(r["total"] or 0)))
    return {
        "period": period,
        "rows": rows,
        "dimensions": [{"code": c, "name": n, "public": p, "description": desc} for c, n, p, desc in DIMENSIONS],
        "note": "总分 = Σ(维度核定分 × 权重) ÷ Σ(有效权重) + 加分项 − 扣分项。系统按口径算出的是初始参考值，"
               "管理岗可逐维度核定覆盖（单元格可编辑）；无数据且未核定的维度不计入并自动归一；"
               "公共维度（知识/积分）无贡献计 0 分。维度口径为 v1 默认实现，可在「计分规则」页调整。",
    }
