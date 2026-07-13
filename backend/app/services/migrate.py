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


def migrate_m35_org(db: Session):
    if db.get_bind().dialect.name != "postgresql":
        return
    ensure_columns(db)
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
