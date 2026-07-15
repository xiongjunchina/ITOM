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
        (2, "方案评估与路径判定", "it_pdm_leader", ["it_dev_leader"], "L3", 72),
        (3, "实现交付（转开发实现 / 转项目管理）", "it_dev_leader", [], "L3", None),
        (4, "验收与闭环", "it_bm", [], "L3", 48),
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


def fix_acceptance_step_role_m165(db: Session):
    """M16.5：需求流程「验收与闭环」处理角色 it_pdm→it_bm（业务域负责人组织业务验收）。"""
    n = db.execute(text(
        "UPDATE process_step SET default_role='it_bm' "
        "WHERE name='验收与闭环' AND default_role='it_pdm' AND is_deleted=false"
    )).rowcount
    if n:
        logger.info("验收与闭环步骤角色 -> it_bm (%d rows)", n)
    db.commit()


def fix_ops_leader_m166(db: Session):
    """M16.6：IT运维负责人接管 事件关闭复盘 / 变更复盘(PIR)；变更审批角色补 it_op_leader。"""
    n1 = db.execute(text(
        "UPDATE process_step ps SET default_role='it_op_leader' "
        "FROM process_definition d WHERE ps.definition_id=d.id AND ps.is_deleted=false "
        "AND ((d.code LIKE 'incident_flow%' AND ps.name='关闭复盘' AND ps.default_role='it_tm') "
        "  OR (d.code LIKE 'change_flow%' AND ps.name='变更复盘(PIR)' AND ps.default_role='it_tm'))"
    )).rowcount
    n2 = db.execute(text(
        "UPDATE workflow_transition SET allowed_roles = allowed_roles || '[\"it_op_leader\"]'::jsonb "
        "WHERE entity_type='ticket_change' AND from_code='pending_approval' "
        "AND NOT (allowed_roles @> '[\"it_op_leader\"]'::jsonb) AND is_deleted=false"
    )).rowcount
    if n1 or n2:
        logger.info("it_op_leader 接线：复盘步骤 %d 处，变更审批流转 %d 条", n1, n2)
    db.commit()


def fix_delivery_step_branches_m167(db: Session):
    """M16.7：需求流程「实现交付」节点展示两条路径（转开发/转项目），fallback 升开发负责人。"""
    n = db.execute(text(
        "UPDATE process_step ps SET "
        "name='实现交付（转开发实现 / 转项目管理）', default_role='it_dev_leader', "
        "description='两种路径由方案评估判定并自动指派：转开发实现→开发负责人（任务清单排期交付）；转项目管理→项目经理（项目立项交付，验收关闭后回传）' "
        "FROM process_definition d WHERE ps.definition_id=d.id AND d.code LIKE 'requirement_flow%' "
        "AND ps.name LIKE '实现交付%' AND ps.is_deleted=false AND ps.default_role IN ('it_dev','it_dev_leader')"
    )).rowcount
    if n:
        logger.info("实现交付节点路径化展示 (%d rows)", n)
    db.commit()


def split_permission_modules_m172(db: Session):
    """M17.2：权限模块按菜单页拆分的存量迁移（幂等，以旧行存在为触发）。

    - tickets → ticket_sr/ticket_incident/ticket_change：requester 仅保留服务请求
      （业务用户不可发起变更/登记事件）；其余角色三行等权复制（能力不缩水，可再收紧）
    - requirements 行衍生：req_tasks 等权复制、req_scoring 只读（requester 均不给——
      业务用户可登记需求，但不可见任务跟踪与评分规则）
    """
    rows = db.execute(text(
        "SELECT role_code, actions FROM role_permission WHERE module='tickets' AND is_deleted=false"
    )).fetchall()
    if rows:
        from app.core.glid import new_glid
        import json as _json
        for role_code, actions in rows:
            targets = ["ticket_sr"] if role_code == "requester" else [
                "ticket_sr", "ticket_incident", "ticket_change"]
            for m in targets:
                exists = db.execute(text(
                    "SELECT 1 FROM role_permission WHERE role_code=:r AND module=:m AND is_deleted=false"
                ), {"r": role_code, "m": m}).first()
                if not exists:
                    db.execute(text(
                        "INSERT INTO role_permission (id, role_code, module, actions, is_deleted, is_example, created_at, updated_at) "
                        "VALUES (:id, :r, :m, CAST(:a AS jsonb), false, false, now(), now())"
                    ), {"id": new_glid(), "r": role_code, "m": m,
                        "a": _json.dumps(actions if isinstance(actions, list) else actions)})
        db.execute(text("DELETE FROM role_permission WHERE module='tickets'"))
        logger.info("tickets 权限拆分为按类型模块（%d 角色，requester 仅服务请求）", len(rows))

    req_rows = db.execute(text(
        "SELECT role_code, actions FROM role_permission WHERE module='requirements' AND is_deleted=false AND role_code != 'requester'"
    )).fetchall()
    if req_rows:
        from app.core.glid import new_glid
        import json as _json
        added = 0
        for role_code, actions in req_rows:
            for m, acts in (("req_tasks", actions), ("req_scoring", ["view"])):
                exists = db.execute(text(
                    "SELECT 1 FROM role_permission WHERE role_code=:r AND module=:m AND is_deleted=false"
                ), {"r": role_code, "m": m}).first()
                if not exists:
                    db.execute(text(
                        "INSERT INTO role_permission (id, role_code, module, actions, is_deleted, is_example, created_at, updated_at) "
                        "VALUES (:id, :r, :m, CAST(:a AS jsonb), false, false, now(), now())"
                    ), {"id": new_glid(), "r": role_code, "m": m,
                        "a": _json.dumps(acts if isinstance(acts, list) else acts)})
                    added += 1
        if added:
            logger.info("需求域衍生权限 req_tasks/req_scoring 补种 %d 行（requester 不授予）", added)
    db.commit()


def close_completed_process_tickets_m23(db: Session):
    """M23 存量修复：流程实例已完成但工单仍停在中间状态（如变更复盘完毕却显示待审批）→ 自动闭环。

    幂等：终态（closed/rejected）工单跳过；沿状态机路径推进（系统级，忽略角色限制）。
    """
    from app.models import AuthUser, ProcessInstance, Ticket
    from app.services.tickets import auto_close_on_process_complete

    admin = db.query(AuthUser).filter(AuthUser.username == "admin").first()
    if not admin:
        return
    fixed = 0
    for inst in (
        db.query(ProcessInstance)
        .filter(
            ProcessInstance.entity_type.in_(["ticket", "ticket_change"]),
            ProcessInstance.status == "已完成",
            ProcessInstance.is_deleted.is_(False),
        )
        .all()
    ):
        t = db.get(Ticket, inst.entity_id)
        if not t or t.is_deleted or t.is_example or t.status in ("closed", "rejected"):
            continue
        if auto_close_on_process_complete(db, t.id, admin):
            fixed += 1
    if fixed:
        logger.info("流程已完成的工单自动闭环 %d 张（M23）", fixed)


def migrate_m35_org(db: Session):
    if db.get_bind().dialect.name != "postgresql":
        return
    ensure_columns(db)
    drop_columns(db)
    fix_project_flow_pmo(db)
    rebuild_requirement_flow_m16(db)
    fix_solution_review_roles_m163(db)
    fix_acceptance_step_role_m165(db)
    fix_ops_leader_m166(db)
    fix_delivery_step_branches_m167(db)
    split_permission_modules_m172(db)
    close_completed_process_tickets_m23(db)
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
