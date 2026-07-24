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
    "position": [
        ("position_code", "VARCHAR(32)"),
        ("position_family", "VARCHAR(32)"),
        ("service_domains", "JSONB NOT NULL DEFAULT '[]'::jsonb"),
        ("primary_roles", "JSONB NOT NULL DEFAULT '[]'::jsonb"),
        ("level_framework", "VARCHAR(64)"),
        ("location_scope", "VARCHAR(128)"),
        ("skills", "TEXT"),
        ("contractor_allowed", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("status", "VARCHAR(16) NOT NULL DEFAULT '启用'"),
        ("sort", "INTEGER NOT NULL DEFAULT 0"),
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
        ("password_set_at", "TIMESTAMP"),  # M36.2 个人安全设置
        ("initial_password_ciphertext", "TEXT"),
        ("initial_password_sent_at", "TIMESTAMP"),
    ],
    "user_group": [
        ("roles", "JSONB NOT NULL DEFAULT '[]'::jsonb"),
        ("owner_id", "VARCHAR(26)"),
    ],
    "process_step": [
        ("cc_roles", "JSONB NOT NULL DEFAULT '[]'::jsonb"),
        ("node_type", "VARCHAR(16) NOT NULL DEFAULT 'processing'"),
        ("step_code", "VARCHAR(64)"),
    ],
    "process_task": [
        ("definition_version", "INTEGER"),
        ("step_code_snapshot", "VARCHAR(64)"),
        ("raci_snapshot", "JSONB"),
        ("completed_by", "VARCHAR(26)"),
    ],
    "point_rule": [
        ("contribution_bucket", "VARCHAR(24) NOT NULL DEFAULT 'team_contribution'"),
        ("contribution_dimension", "VARCHAR(48)"),
        ("target_points", "DOUBLE PRECISION"),
    ],
    "point_entry": [
        ("contribution_bucket", "VARCHAR(24) NOT NULL DEFAULT 'team_contribution'"),
        ("contribution_dimension", "VARCHAR(48)"),
    ],
    "performance_role_assignment": [
        ("evaluator_weights", "JSONB NOT NULL DEFAULT '{}'::jsonb"),
    ],
    "performance_score_component": [
        ("manager_scores", "JSONB NOT NULL DEFAULT '{}'::jsonb"),
        ("manager_reasons", "JSONB NOT NULL DEFAULT '{}'::jsonb"),
        ("manager_evidence_refs", "JSONB NOT NULL DEFAULT '{}'::jsonb"),
    ],
    "knowledge_article": [
        ("content_format", "VARCHAR(8) NOT NULL DEFAULT 'markdown'"),
    ],
    "problem": [
        ("assigned_line", "VARCHAR(16)"),
        ("reporter", "VARCHAR(26)"),
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


def backfill_process_step_codes(db: Session):
    """M78：为历史流程步骤补齐版本内稳定编码，避免名称/序号变更破坏取数映射。"""
    rows = db.execute(text(
        "SELECT ps.id, ps.definition_id, ps.seq FROM process_step ps "
        "WHERE ps.is_deleted=false AND (ps.step_code IS NULL OR ps.step_code='') "
        "ORDER BY ps.definition_id, ps.seq"
    )).fetchall()
    for step_id, definition_id, seq in rows:
        db.execute(text("UPDATE process_step SET step_code=:code WHERE id=:id"), {
            "id": step_id, "code": f"step_{seq}",
        })
    if rows:
        logger.info("M78：为 %d 个历史流程节点补齐 step_code", len(rows))
    db.commit()


def separate_role_result_point_entries(db: Session):
    """M78：把历史 ITSM/需求/项目结果流水明确归入 role_result。"""
    role_events = (
        "ticket_resolved", "ticket_sla_met", "ticket_satisfaction",
        "wbs_done_on_time", "milestone_achieved", "requirement_task_done", "requirement_closed",
    )
    changed = db.execute(text(
        "UPDATE point_entry SET contribution_bucket='role_result' "
        "WHERE source_type = ANY(:codes) AND is_deleted=false"
    ), {"codes": list(role_events)}).rowcount
    if changed:
        logger.info("M78：将 %d 条 ITSM/需求/项目积分流水隔离为 role_result", changed)
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


def fix_pmo_performance_review_mode(db: Session):
    """M77：IT PMO 自身由 CIO 直评，存量未发布周期同步该规则。

    已发布/锁定周期属于历史快照，不改写；下一次重算会按新的角色档案生成
    CIO 直评快照。存量未发布 assignment 清除普通评审人的范围，避免旧配置
    继续把 PMO 暴露给专业线负责人初评。
    """
    profile = db.execute(text(
        "UPDATE performance_role_profile "
        "SET review_mode='cio_direct' "
        "WHERE role_code='it_pmo' AND is_deleted=false AND review_mode <> 'cio_direct'"
    ))
    assignments = db.execute(text(
        "UPDATE performance_role_assignment a "
        "SET review_mode='cio_direct', evaluator_ids='[]'::jsonb, "
        "    review_scope=COALESCE(a.review_scope, '{}'::jsonb) - 'evaluator_ids' "
        "FROM performance_period p "
        "WHERE a.period_id=p.id AND a.role_code='it_pmo' AND a.is_deleted=false "
        "  AND p.is_deleted=false AND p.status NOT IN ('published', 'locked') "
        "  AND a.review_mode <> 'cio_direct'"
    ))
    if profile.rowcount or assignments.rowcount:
        logger.info(
            "M77：IT PMO 改为 CIO 直评（profile=%d, assignments=%d）",
            profile.rowcount, assignments.rowcount,
        )
    db.commit()


def fix_process_node_types_m75(db: Session):
    """M75：为六条内置流程补齐审批/处理节点语义。"""
    approval_steps = {
        "incident_flow": ("受理定级", "解决与用户确认"),
        "sr_flow": ("用户确认关闭",),
        "change_flow": ("风险评估", "变更审批"),
        "problem_flow": ("问题确认", "解决确认与关闭"),
        "project_flow": ("立项启动", "收尾复盘"),
        "requirement_flow": ("需求评审（业务域负责人）", "方案评估与路径判定", "验收与闭环"),
    }
    changed = 0
    for code, names in approval_steps.items():
        for name in names:
            result = db.execute(text(
                "UPDATE process_step ps SET node_type='approval' "
                "FROM process_definition pd "
                "WHERE ps.definition_id=pd.id AND pd.code LIKE :code "
                "AND ps.name=:name AND ps.is_deleted=false"
            ), {"code": f"{code}%", "name": name})
            changed += result.rowcount or 0
    if changed:
        logger.info("M75：内置流程审批节点补齐 %d 个", changed)
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
    """M16.6 历史兼容：旧定义中的复盘曾由 it_tm 处理，迁移时改为 it_op_leader；
    当前运行时若已由流程中心配置为 is_mgr，不覆盖该已发布定义；同时补齐变更审批的 it_op_leader 状态机授权。"""
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
            ProcessInstance.status.in_(["completed", "已完成"]),
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


def sync_process_status_m24(db: Session):
    """M24 存量修复：流程线与状态机双向脱节的历史数据。

    正向：问题流程已完成但问题未终态 → 自动闭环；
    反向：单据已终态（工单/问题/需求/项目）但流程实例仍 running → 收尾作废剩余待办。
    幂等：均只处理不一致行。
    """
    from app.models import AuthUser, ProcessInstance, Problem, Project, Requirement, Ticket
    from app.services import process_engine
    from app.routers.problems import auto_close_problem_on_process_complete

    # 实例状态值归一（历史混用：模型默认「进行中」、重启写 running、完成写「已完成」；
    # 前端筛选一直发英文 code——统一库内为英文，监控页筛选自此生效）
    normalized = db.execute(text("UPDATE process_instance SET status='running' WHERE status='进行中'")).rowcount
    normalized += db.execute(text("UPDATE process_instance SET status='completed' WHERE status='已完成'")).rowcount
    if normalized:
        logger.info("流程实例状态值归一为英文 code %d 行（M24）", normalized)

    admin = db.query(AuthUser).filter(AuthUser.username == "admin").first()
    if not admin:
        return
    closed_problems = 0
    for inst in (
        db.query(ProcessInstance)
        .filter(ProcessInstance.entity_type == "problem", ProcessInstance.status.in_(["completed", "已完成"]),
                ProcessInstance.is_deleted.is_(False))
        .all()
    ):
        p = db.get(Problem, inst.entity_id)
        if p and not p.is_deleted and not p.is_example and p.status != "closed":
            if auto_close_problem_on_process_complete(db, p.id, admin):
                closed_problems += 1

    finalized = 0
    terminal = {
        "ticket": (Ticket, ("closed", "rejected")),
        "ticket_change": (Ticket, ("closed", "rejected")),
        "problem": (Problem, ("closed",)),
        "requirement": (Requirement, ("closed", "cancelled")),
        "project": (Project, ("closed", "cancelled")),
    }
    for inst in (
        db.query(ProcessInstance)
        .filter(ProcessInstance.status.in_(["running", "进行中"]), ProcessInstance.is_deleted.is_(False))
        .all()
    ):
        model_terminal = terminal.get(inst.entity_type)
        if not model_terminal:
            continue
        model, terminal_statuses = model_terminal
        entity = db.get(model, inst.entity_id)
        if entity and not entity.is_deleted and getattr(entity, "is_example", False) is False \
                and entity.status in terminal_statuses:
            process_engine.finalize_instance(db, inst.entity_type, inst.entity_id, "单据已终态，流程随单收尾（M24 存量修复）")
            finalized += 1
    if closed_problems or finalized:
        db.commit()
        logger.info("流程/状态机双向同步修复：问题闭环 %d 个，收尾 running 实例 %d 个（M24）", closed_problems, finalized)


def rebuild_problem_flow_m29(db: Session):
    """M29：问题流程重构（确认→根因分析→解决验证→解决确认关闭，专业线动态指派）。

    有历史实例（用户 PB-202607-0001 等）→ 另存新版本激活、旧版停用（老单沿旧版展示）；
    无实例 → 直接重建步骤。幂等：激活定义首步含新说明则跳过。
    """
    import json as _json

    row = db.execute(text(
        "SELECT id, code, version FROM process_definition "
        "WHERE code LIKE 'problem_flow%' AND active=true AND is_deleted=false ORDER BY version DESC LIMIT 1"
    )).first()
    if not row:
        return
    def_id, code, version = row
    first_desc = db.execute(text(
        "SELECT description FROM process_step WHERE definition_id=:d AND is_deleted=false ORDER BY seq LIMIT 1"
    ), {"d": def_id}).scalar()
    if first_desc and "专业线" in first_desc:
        return  # 已是新版
    steps = [
        (1, "问题确认", "L3", 24, "按问题所属专业线自动指派对应负责人；不属实可驳回退回提单人（必填理由）"),
        (2, "根因分析", "L3", None, "确认属实时由专业线负责人指定处理人"),
        (3, "解决与验证", "L3", None, "延续根因分析处理人"),
        (4, "解决确认与关闭", "L2", 24, "专业线负责人确认已解决并登记关闭说明，完成后问题自动关闭"),
    ]
    used = db.execute(text("SELECT count(*) FROM process_instance WHERE definition_id=:d"), {"d": def_id}).scalar()
    if used:
        new_ver = (version or 1) + 1
        new_id = new_glid()
        db.execute(text(
            "INSERT INTO process_definition (id, code, name, entity_type, version, active, is_deleted, is_example, created_at, updated_at) "
            "VALUES (:id, :code, '问题分析流程', 'problem', :ver, true, false, false, now(), now())"
        ), {"id": new_id, "code": f"problem_flow@v{new_ver}", "ver": new_ver})
        db.execute(text("UPDATE process_definition SET active=false WHERE id=:d"), {"d": def_id})
        target = new_id
    else:
        db.execute(text("DELETE FROM process_step WHERE definition_id=:d"), {"d": def_id})
        target = def_id
    for seq, name, level, sla, desc in steps:
        db.execute(text(
            "INSERT INTO process_step (id, definition_id, seq, name, default_role, cc_roles, autonomy_level, sla_hours, description, is_deleted, is_example, created_at, updated_at) "
            "VALUES (:id, :d, :seq, :name, NULL, '[]'::jsonb, :level, :sla, :desc, false, false, now(), now())"
        ), {"id": new_glid(), "d": target, "seq": seq, "name": name, "level": level, "sla": sla, "desc": desc})
    logger.info("problem_flow 已重构为 M29 四步流程（%s）", "新版本激活" if used else "原定义重建")
    db.commit()


def rename_feishu_scope_m32(db: Session):
    """M32：feishu_config.it_department_id → sync_scope（语义扩展为同步范围，保留原值）。"""
    cols = _columns(db, "feishu_config")
    if "it_department_id" in cols and "sync_scope" not in cols:
        db.execute(text("ALTER TABLE feishu_config RENAME COLUMN it_department_id TO sync_scope"))
        db.execute(text("ALTER TABLE feishu_config ALTER COLUMN sync_scope TYPE VARCHAR(512)"))
        logger.info("feishu_config.it_department_id -> sync_scope（M32 同步范围）")
        db.commit()


def drop_notification_recipient_fk_m34(db: Session):
    """M34：通知收件人改双语义（人员 id 或账号 id）——删除到 org_member 的外键约束。"""
    row = db.execute(text(
        "SELECT conname FROM pg_constraint WHERE conrelid='in_app_notification'::regclass "
        "AND contype='f' AND conname LIKE '%recipient%'"
    )).first()
    if row:
        db.execute(text(f"ALTER TABLE in_app_notification DROP CONSTRAINT {row.conname}"))
        logger.info("已删除 in_app_notification.recipient 外键（M34 双语义收件）")
        db.commit()


def widen_department_sort_m341(db: Session):
    """M34.1：飞书部门 order 为超大整数（>int32），department.sort 扩为 BIGINT。"""
    row = db.execute(text(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name='department' AND column_name='sort'"
    )).first()
    if row and row.data_type == "integer":
        db.execute(text("ALTER TABLE department ALTER COLUMN sort TYPE BIGINT"))
        logger.info("department.sort -> BIGINT（M34.1 飞书 order 溢出修复）")
        db.commit()


def backfill_password_set_m362(db: Session):
    """M36.2：存量本地账号口令视为已人为设定（创建即告知本人），改密需验当前密码。"""
    db.execute(text(
        "UPDATE auth_user SET password_set_at = created_at "
        "WHERE auth_source = 'local' AND password_set_at IS NULL"
    ))
    db.commit()


def grant_cio_position_delete(db: Session):
    """岗位编制由 CIO 与系统管理员共同维护（补齐存量权限矩阵）。"""
    result = db.execute(text(
        "UPDATE role_permission "
        "SET actions = CASE "
        "WHEN actions @> '[\"delete\"]'::jsonb THEN actions "
        "ELSE actions || '[\"delete\"]'::jsonb END "
        "WHERE role_code='cio' AND module='positions' AND is_deleted=false"
    ))
    if result.rowcount:
        logger.info("岗位编制：已为 CIO 补齐删除权限 (%d rows)", result.rowcount)
    db.commit()


def grant_cio_external_input_delete(db: Session):
    """外部绩效原数据支持修订/删除，补齐 CIO 存量权限矩阵。"""
    result = db.execute(text(
        "UPDATE role_permission "
        "SET actions = CASE "
        "WHEN actions @> '[\"delete\"]'::jsonb THEN actions "
        "ELSE actions || '[\"delete\"]'::jsonb END "
        "WHERE role_code='cio' AND module='performance_external' AND is_deleted=false"
    ))
    if result.rowcount:
        logger.info("人效外部原数据：已为 CIO 补齐删除权限 (%d rows)", result.rowcount)
    db.commit()


def backfill_wbs_progress_hierarchy(db: Session):
    """M76：将存量 WBS 父级完成度统一回算为直接子项平均值。

    新规则只允许显式 100% 触发向下级联，历史数据中父级可能仍保存着旧的手工比例；
    启动时幂等回填一次，避免旧项目在首次编辑前展示不一致的父子进度。
    """
    from app.models import WbsTask
    from app.services.projects import recalculate_wbs_hierarchy

    tasks = db.query(WbsTask).filter(WbsTask.is_deleted.is_(False)).all()
    by_project: dict[str, list[WbsTask]] = {}
    for task in tasks:
        by_project.setdefault(task.project_id, []).append(task)

    changed = sum(len(recalculate_wbs_hierarchy(project_tasks)) for project_tasks in by_project.values())
    if changed:
        logger.info("M76：回算存量 WBS 父级完成度 %d 行", changed)
        db.commit()


def migrate_m35_org(db: Session):
    if db.get_bind().dialect.name != "postgresql":
        return
    rename_feishu_scope_m32(db)
    drop_notification_recipient_fk_m34(db)
    widen_department_sort_m341(db)
    ensure_columns(db)
    backfill_process_step_codes(db)
    separate_role_result_point_entries(db)
    backfill_password_set_m362(db)
    grant_cio_position_delete(db)
    grant_cio_external_input_delete(db)
    backfill_wbs_progress_hierarchy(db)
    drop_columns(db)
    fix_project_flow_pmo(db)
    fix_pmo_performance_review_mode(db)
    rebuild_requirement_flow_m16(db)
    fix_solution_review_roles_m163(db)
    fix_acceptance_step_role_m165(db)
    fix_ops_leader_m166(db)
    fix_delivery_step_branches_m167(db)
    split_permission_modules_m172(db)
    close_completed_process_tickets_m23(db)
    sync_process_status_m24(db)
    rebuild_problem_flow_m29(db)
    fix_process_node_types_m75(db)
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
