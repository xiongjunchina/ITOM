"""学习成长目标与团队贡献积分同步。"""

from sqlalchemy.orm import Session

from app.models import LearningGrowthGoal, PointEntry

# learning_growth 是团队贡献中的一个维度，目标积分与现有 TEAM_TARGETS 保持一致。
LEARNING_GROWTH_TARGET_POINTS = 30.0


def sync_learning_growth_points(
    db: Session,
    person_id: str,
    period: str,
    created_by: str | None = None,
) -> None:
    """按同一员工/周期的目标平均完成比例重建积分流水。

    多个目标按等权平均处理，避免新增目标后简单累加导致超过该维度目标积分。
    每个目标仍保留一条可追溯的积分流水；历史流水软删，当前有效流水保持幂等。
    """

    # SessionLocal 使用 autoflush=False；先把新增、修改或软删目标刷入事务，
    # 否则本次回算会读到旧的目标数量/进度。
    db.flush()
    goals = (
        db.query(LearningGrowthGoal)
        .filter(
            LearningGrowthGoal.person_id == person_id,
            LearningGrowthGoal.period == period,
            LearningGrowthGoal.is_deleted.is_(False),
        )
        .order_by(LearningGrowthGoal.created_at, LearningGrowthGoal.id)
        .all()
    )
    old_entries = (
        db.query(PointEntry)
        .filter(
            PointEntry.person_id == person_id,
            PointEntry.period == period,
            PointEntry.source_type == "learning_growth",
            PointEntry.is_deleted.is_(False),
        )
        .all()
    )
    for entry in old_entries:
        entry.is_deleted = True

    share = LEARNING_GROWTH_TARGET_POINTS / len(goals) if goals else 0
    for goal in goals:
        points = round(max(0.0, min(100.0, goal.progress or 0.0)) / 100 * share, 2)
        goal.points = points
        db.add(
            PointEntry(
                person_id=person_id,
                points=points,
                source_type="learning_growth",
                source_ref=goal.id,
                period=period,
                contribution_bucket="team_contribution",
                contribution_dimension="learning_growth",
                note=f"学习成长：{goal.goal[:150]}",
                created_by=created_by,
            )
        )
