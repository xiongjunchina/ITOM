"""轻量结构迁移：启动时在 create_all 之后执行（幂等，PG 专用，sqlite 测试库跳过）。

M3.5：org_member 的 dept/team 自由文本列 → department 表 / 用户组成员关系，然后删列。
"""
import logging

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.glid import new_glid

logger = logging.getLogger("aom.migrate")


def _columns(db: Session, table: str) -> set[str]:
    return {c["name"] for c in inspect(db.get_bind()).get_columns(table)}


ENSURE_COLUMNS = {
    # create_all 不会给已有表补列，这里显式补齐 M3.5 新列
    "org_member": [
        ("name_en", "VARCHAR(64)"),
        ("department_id", "VARCHAR(26)"),
        ("mobile", "VARCHAR(32)"),
        ("external_source", "VARCHAR(16)"),
        ("external_id", "VARCHAR(128)"),
        ("employee_no", "VARCHAR(32)"),
        ("gender", "VARCHAR(8)"),
        ("birth_date", "DATE"),
        ("employment_type", "VARCHAR(16)"),
        ("supervisor_id", "VARCHAR(26)"),
        ("work_location", "VARCHAR(64)"),
    ],
    "wbs_task": [
        ("stage", "VARCHAR(64)"),
        ("wbs_dict", "TEXT"),
        ("is_milestone", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("actual_start", "DATE"),
        ("actual_end", "DATE"),
        ("progress", "INTEGER NOT NULL DEFAULT 0"),
        ("remarks", "TEXT"),
    ],
    "hiring_need": [
        ("level", "VARCHAR(8) NOT NULL DEFAULT '中级'"),
        ("qualification", "TEXT"),
    ],
    "requirement_scoring_config": [
        ("effort_threshold", "DOUBLE PRECISION"),
        ("review_assignees", "JSONB"),
    ],
    "requirement": [
        ("solution_type", "VARCHAR(16)"),
        ("department", "VARCHAR(64)"),
        ("expected_date", "DATE"),
        ("expected_effect", "TEXT"),
        ("business_value_note", "TEXT"),
        ("score_d1_strategy", "INTEGER"),
        ("score_d2_value", "INTEGER"),
        ("score_d3_tech", "INTEGER"),
        ("score_d4_org", "INTEGER"),
        ("score_d5_risk", "INTEGER"),
        ("score_d6_speed", "INTEGER"),
        ("decision", "VARCHAR(16)"),
        ("prd_effort", "DOUBLE PRECISION"),
        ("dev_effort", "DOUBLE PRECISION"),
        ("evaluating_at", "TIMESTAMP"),
    ],
    "project": [
        ("background", "TEXT"),
        ("goals", "TEXT"),
        ("scope_in", "TEXT"),
        ("scope_out", "TEXT"),
        ("resource_note", "TEXT"),
        ("org_members", "JSONB"),
        ("stakeholders", "JSONB"),
    ],
    "requirement_task": [
        ("description", "TEXT"),
        ("plan_effort", "DOUBLE PRECISION"),
        ("actual_effort", "DOUBLE PRECISION"),
    ],
    "auth_user": [
        ("preferences", "JSONB NOT NULL DEFAULT '{}'::jsonb"),
        ("auth_source", "VARCHAR(16) NOT NULL DEFAULT 'local'"),
        ("external_id", "VARCHAR(128)"),
    ],
    "user_group": [
        ("roles", "JSONB NOT NULL DEFAULT '[]'::jsonb"),
        ("owner_id", "VARCHAR(26)"),
    ],
    "process_step": [
        ("cc_roles", "JSONB NOT NULL DEFAULT '[]'::jsonb"),
    ],
    "knowledge_article": [
        ("content_format", "VARCHAR(8) NOT NULL DEFAULT 'markdown'"),
    ],
}


def ensure_is_example_everywhere(db: Session):
    """GlidBase 新增 is_example：为存量所有业务表补列（create_all 不加列）。"""
    from app.db import Base

    inspector = inspect(db.get_bind())
    existing_tables = set(inspector.get_table_names())
    for table in Base.metadata.tables:
        if table not in existing_tables:
            continue
        if "is_example" not in _columns(db, table):
            db.execute(text(f"ALTER TABLE {table} ADD COLUMN is_example BOOLEAN NOT NULL DEFAULT false"))
            logger.info("added column %s.is_example", table)
    db.commit()


def ensure_columns(db: Session):
    for table, columns in ENSURE_COLUMNS.items():
        existing = _columns(db, table)
        for name, ddl in columns:
            if name not in existing:
                db.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                logger.info("added column %s.%s", table, name)
    db.commit()


# 已废弃、需从存量表删除的列（create_all 不会删列）
DROP_COLUMNS = {
    "wbs_task": ["status"],  # M9：状态改为据完成度与计划结束日计算，不再落库
}


def drop_columns(db: Session):
    for table, cols in DROP_COLUMNS.items():
        existing = _columns(db, table)
        for name in cols:
            if name in existing:
                db.execute(text(f"ALTER TABLE {table} DROP COLUMN {name}"))
                logger.info("dropped column %s.%s", table, name)
    db.commit()


def fix_project_flow_pmo(db: Session):
    """M12：项目流程「收尾复盘」处理人改 it_pmo（种子幂等不更新存量定义，这里补）。"""
    n = db.execute(text(
        "UPDATE process_step SET default_role='it_pmo' "
        "WHERE name='收尾复盘' AND default_role='it_pm' AND is_deleted=false"
    )).rowcount
    if n:
        logger.info("project_flow 收尾复盘 default_role -> it_pmo (%d rows)", n)
    db.commit()


def rebuild_requirement_flow_m16(db: Session):
    """M16：需求交付流程按新语义重构（评审→方案评估→实现→验收）。

    仅当该流程无任何实例（含软删）时执行——需求域 M16 前已清库；有实例的环境跳过，
    由管理员在流程定义页「另存新版本」迁移。幂等：首步骤名已是新版则跳过。
    """
    row = db.execute(text(
        "SELECT d.id FROM process_definition d WHERE d.code='requirement_flow' AND d.is_deleted=false"
    )).first()
    if not row:
        return
    def_id = row[0]
    first = db.execute(text(
        "SELECT name FROM process_step WHERE definition_id=:d AND is_deleted=false ORDER BY seq LIMIT 1"
    ), {"d": def_id}).scalar()
    if first and "需求评审" in first:
        return  # 已是新版
    used = db.execute(text(
        "SELECT count(*) FROM process_instance WHERE definition_id=:d"), {"d": def_id}).scalar()
    if used:
        logger.warning("requirement_flow 有 %s 个历史实例，跳过自动重构（请另存新版本）", used)
        return
    db.execute(text("DELETE FROM process_step WHERE definition_id=:d"), {"d": def_id})
    from app.core.glid import new_glid
    steps = [
        (1, "需求评审（业务域负责人）", "it_bm", ["it_pdm"], "L3", 48),
        (2, "方案评估与路径判定", "it_tm", ["it_dev"], "L3", 72),
        (3, "实现交付（开发/项目跟踪）", "it_dev", [], "L3", None),
        (4, "验收与闭环", "it_pdm", [], "L3", 48),
    ]
    import json as _json
    for seq, name, role, cc, level, sla in steps:
        db.execute(text(
            "INSERT INTO process_step (id, definition_id, seq, name, default_role, cc_roles, autonomy_level, sla_hours, is_deleted, is_example, created_at, updated_at) "
            "VALUES (:id, :d, :seq, :name, :role, CAST(:cc AS jsonb), :level, :sla, false, false, now(), now())"
        ), {"id": new_glid(), "d": def_id, "seq": seq, "name": name, "role": role,
            "cc": _json.dumps(cc), "level": level, "sla": sla})
    logger.info("requirement_flow 已重构为 M16 四步流程")
    db.commit()


def fix_solution_review_roles_m163(db: Session):
    """M16.3：方案评估步骤主责/知会换 it_pdm_leader/it_dev_leader（等长更新，实例安全）。"""
    n = db.execute(text(
        "UPDATE process_step SET default_role='it_pdm_leader', cc_roles='[\"it_dev_leader\"]'::jsonb "
        "WHERE name='方案评估与路径判定' AND default_role='it_tm' AND is_deleted=false"
    )).rowcount
    if n:
        logger.info("方案评估步骤角色 -> it_pdm_leader/it_dev_leader (%d rows)", n)
    db.commit()


def migrate_m35_org(db: Session):
    if db.get_bind().dialect.name != "postgresql":
        return
    ensure_columns(db)
    drop_columns(db)
    fix_project_flow_pmo(db)
    rebuild_requirement_flow_m16(db)
    fix_solution_review_roles_m163(db)
    ensure_is_example_everywhere(db)
    cols = _columns(db, "org_member")

    if "dept" in cols:
        rows = db.execute(
            text("SELECT id, dept FROM org_member WHERE dept IS NOT NULL AND dept != '' AND department_id IS NULL")
        ).fetchall()
        for member_id, dept_name in rows:
            dept_id = db.execute(
                text("SELECT id FROM department WHERE name = :n AND is_deleted = false"), {"n": dept_name}
            ).scalar()
            if not dept_id:
                dept_id = new_glid()
                dept_type = "it" if "IT" in dept_name.upper() else "business"
                db.execute(
                    text(
                        "INSERT INTO department (id, code, name, dept_type, sort, active, is_deleted, created_at, updated_at) "
                        "VALUES (:id, :code, :name, :t, 0, true, false, now(), now())"
                    ),
                    {"id": dept_id, "code": f"D{dept_id[-8:]}", "name": dept_name, "t": dept_type},
                )
            db.execute(
                text("UPDATE org_member SET department_id = :d WHERE id = :m"), {"d": dept_id, "m": member_id}
            )
        db.execute(text("ALTER TABLE org_member DROP COLUMN dept"))
        logger.info("migrated org_member.dept -> department (%d rows)", len(rows))

    if "team" in cols:
        rows = db.execute(
            text("SELECT id, team FROM org_member WHERE team IS NOT NULL AND team != ''")
        ).fetchall()
        for member_id, team_name in rows:
            group_id = db.execute(
                text("SELECT id FROM user_group WHERE name = :n AND is_deleted = false"), {"n": team_name}
            ).scalar()
            if not group_id:
                group_id = new_glid()
                db.execute(
                    text(
                        "INSERT INTO user_group (id, code, name, description, roles, is_deleted, created_at, updated_at) "
                        "VALUES (:id, :code, :name, '由原 team 字段迁移', '[]'::jsonb, false, now(), now())"
                    ),
                    {"id": group_id, "code": f"g{group_id[-8:].lower()}", "name": team_name},
                )
            exists = db.execute(
                text("SELECT 1 FROM user_group_member WHERE group_id = :g AND person_id = :p"),
                {"g": group_id, "p": member_id},
            ).scalar()
            if not exists:
                db.execute(
                    text(
                        "INSERT INTO user_group_member (id, group_id, person_id, is_deleted, created_at, updated_at) "
                        "VALUES (:id, :g, :p, false, now(), now())"
                    ),
                    {"id": new_glid(), "g": group_id, "p": member_id},
                )
        db.execute(text("ALTER TABLE org_member DROP COLUMN team"))
        logger.info("migrated org_member.team -> user_group (%d rows)", len(rows))

    db.commit()


def run_migrations(db: Session):
    try:
        migrate_m35_org(db)
    except Exception:
        db.rollback()
        logger.exception("migration failed")
        raise
