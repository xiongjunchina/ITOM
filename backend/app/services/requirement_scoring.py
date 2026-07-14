"""需求六维加权评分与四象限判定（M10）。

依据 docs/需求评分与优先级细化标准.docx：
- 六维：D1 战略对齐 / D2 业务价值 / D3 技术可行性 / D4 组织就绪 / D5 风险(反向) / D6 价值速度
- 加权总分 = Σ w·D，其中风险取 (6−D5) 反向计入
- 四象限：按 加权总分 与 战略价值均值 (D1+D2)/2 两轴判定
权重/阈值/分档由 RequirementScoringConfig 单行配置（系统管理可调，年度复审）。
"""
from app.models import RequirementScoringConfig

DIMENSIONS = ["d1_strategy", "d2_value", "d3_tech", "d4_org", "d5_risk", "d6_speed"]

# 权重表为准（文档正文"风险与速度各10%"为笔误，见评分标准 §1.1 权重表）
DEFAULT_WEIGHTS = {"d1": 0.2, "d2": 0.2, "d3": 0.2, "d4": 0.1, "d5": 0.1, "d6": 0.2}
DEFAULT_THRESHOLDS = {"total": 3.5, "strategic": 4.0, "viable": 3.0}
DEFAULT_ROLE_WEIGHTS = {"业务": 0.4, "技术": 0.3, "PMO": 0.2, "财务": 0.1}
DEFAULT_EFFORT_THRESHOLD = 20.0  # 二开人天≥阈值 或 新购系统 → 转项目管理

SOLUTION_SECONDARY = "二次开发"
SOLUTION_NEW_SYSTEM = "新购系统"
ROUTE_DEV = "需求开发实现"
ROUTE_PROJECT = "转项目管理"

# 四象限规范值（中文为后端权威值，前端 enums 映射英文）
QUADRANT_STRATEGIC = "战略下注"
QUADRANT_QUICK_WIN = "速赢项目"
QUADRANT_LOW = "低优先级"
QUADRANT_REEVALUATE = "重新评估"

DEFAULT_RUBRIC = {
    "d1": {"name": "战略对齐", "5": "直接支撑3年战略TOP3，有战略KPI挂钩", "4": "支撑战略重点，非最核心",
           "3": "方向一致，第二梯队", "2": "关联间接，有则更好", "1": "与战略无明确关联"},
    "d2": {"name": "业务价值", "5": "3年ROI>300%，覆盖营收+成本", "4": "ROI 150~300%，单类价值有KPI",
           "3": "ROI 80~150%，量化有假设", "2": "软性价值难量化", "1": "无法量化商业价值"},
    "d3": {"name": "技术可行性", "5": "成熟SaaS，接口≤3标准协议", "4": "PoC验证过，接口4-6",
           "3": "理论可行未本地验证，接口7-10", "2": "核心技术探索阶段，接口>10", "1": "存在根本性技术障碍"},
    "d4": {"name": "组织就绪度", "5": "业务主动提出，Sponsor承诺配合", "4": "支持但积极性待提升",
           "3": "态度中立需PMO推动", "2": "明确抵触/缺Sponsor", "1": "无Sponsor，纯IT主导"},
    "d5": {"name": "风险等级(反向)", "1": "各风险类别均低，无重大风险", "2": "1-2中等风险有缓解计划",
           "3": "2-3高风险，缓解在制定", "4": "多个高风险，缓解不确定", "5": "根本性风险无缓解路径"},
    "d6": {"name": "价值速度", "5": "上线后≤半月见KPI改善", "4": "1-3个月出首批价值",
           "3": "3-6个月交付核心功能", "2": "6-12个月见价值", "1": ">12个月，播种型投资"},
}


def get_config(db) -> RequirementScoringConfig:
    """取评分配置单行；不存在则创建默认行。"""
    cfg = db.query(RequirementScoringConfig).filter(
        RequirementScoringConfig.is_deleted.is_(False)
    ).first()
    if not cfg:
        cfg = RequirementScoringConfig(
            weights=dict(DEFAULT_WEIGHTS), thresholds=dict(DEFAULT_THRESHOLDS),
            rubric=dict(DEFAULT_RUBRIC), role_weights=dict(DEFAULT_ROLE_WEIGHTS),
            effort_threshold=DEFAULT_EFFORT_THRESHOLD,
        )
        db.add(cfg)
        db.flush()
    return cfg


def compute_weighted_total(scores: dict, weights: dict | None = None) -> float | None:
    """scores: {d1_strategy..d6_speed} 值 1-5；任一维度缺失 → None（未评完）。"""
    w = weights or DEFAULT_WEIGHTS
    vals = {}
    for d in DIMENSIONS:
        v = scores.get(d)
        if v is None:
            return None
        vals[d] = float(v)
    total = (
        w["d1"] * vals["d1_strategy"]
        + w["d2"] * vals["d2_value"]
        + w["d3"] * vals["d3_tech"]
        + w["d4"] * vals["d4_org"]
        + w["d5"] * (6 - vals["d5_risk"])  # 风险反向
        + w["d6"] * vals["d6_speed"]
    )
    return round(total, 2)


def compute_quadrant(scores: dict, thresholds: dict | None = None,
                     weights: dict | None = None) -> str | None:
    """四象限：横轴战略价值 (D1+D2)/2，纵轴加权总分。"""
    total = compute_weighted_total(scores, weights)
    d1, d2 = scores.get("d1_strategy"), scores.get("d2_value")
    if total is None or d1 is None or d2 is None:
        return None
    th = thresholds or DEFAULT_THRESHOLDS
    strategic_value = (float(d1) + float(d2)) / 2
    if total >= th["total"]:
        return QUADRANT_STRATEGIC if strategic_value >= th["strategic"] else QUADRANT_QUICK_WIN
    return QUADRANT_LOW if strategic_value >= th["viable"] else QUADRANT_REEVALUATE


def compute_route(solution_type: str | None, dev_effort: float | None,
                  threshold: float | None = None) -> str | None:
    """实现路径判定（M16，派生不落库）：新购系统 或 二开人天≥阈值 → 转项目管理。"""
    if not solution_type:
        return None
    if solution_type == SOLUTION_NEW_SYSTEM:
        return ROUTE_PROJECT
    th = threshold if threshold is not None else DEFAULT_EFFORT_THRESHOLD
    if dev_effort is not None and dev_effort >= th:
        return ROUTE_PROJECT
    return ROUTE_DEV


def requirement_scores(r) -> dict:
    """从 Requirement 抽取六维分为计算用 dict。"""
    return {
        "d1_strategy": r.score_d1_strategy, "d2_value": r.score_d2_value,
        "d3_tech": r.score_d3_tech, "d4_org": r.score_d4_org,
        "d5_risk": r.score_d5_risk, "d6_speed": r.score_d6_speed,
    }
