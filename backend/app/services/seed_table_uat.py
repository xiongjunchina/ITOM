"""Local-only synthetic data for wide-table browser acceptance.

The dataset is deliberately generated from fictitious values and refuses any
database URL that is not clearly local.  It is never called from application
startup, migrations, or production deployment.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.models import (
    Bug,
    BugFixTask,
    BusinessDomain,
    Ci,
    Department,
    OrgMember,
    Portfolio,
    Position,
    Project,
    ProjectDevelopmentTask,
    Requirement,
    RequirementTask,
    ServiceCatalog,
    ServiceItem,
    Ticket,
    WbsTask,
    WorkTask,
)


UAT_MARKER = "【本地表格UAT】"
LOCAL_DATABASE_HOSTS = {"db", "localhost", "127.0.0.1", "::1"}


def assert_local_uat_database(database_url: str) -> None:
    """Fail closed unless the URL unambiguously targets local SQLite/Compose."""

    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        return
    host = (url.host or "").lower()
    if host not in LOCAL_DATABASE_HOSTS:
        raise RuntimeError("表格 UAT 数据只允许写入本地 SQLite 或 Docker Compose 数据库")


def _upsert(db: Session, model, lookup: dict, values: dict):
    row = db.query(model).filter_by(**lookup).first()
    if row is None:
        row = model(**lookup, **values)
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    row.is_deleted = False
    row.is_example = False
    return row


def seed_table_uat(db: Session) -> dict[str, int]:
    """Create or refresh a deterministic, editable dataset for local UI UAT."""

    assert_local_uat_database(str(db.get_bind().url))
    today = date.today()
    now = datetime.now()

    department = _upsert(
        db,
        Department,
        {"code": "uat_table_it"},
        {"name": f"{UAT_MARKER}信息技术部", "dept_type": "it", "sort": 9900, "active": True},
    )
    position = _upsert(
        db,
        Position,
        {"position_code": "UAT-TABLE-DEV"},
        {
            "name": f"{UAT_MARKER}全栈工程师",
            "position_family": "技术",
            "duties": "仅用于本地宽表、固定列与操作按钮验收",
            "headcount": 2,
            "primary_roles": ["it_dev", "it_pm", "it_ops"],
            "status": "启用",
        },
    )
    db.flush()
    member = _upsert(
        db,
        OrgMember,
        {"employee_no": "UAT-TABLE-001"},
        {
            "name": f"{UAT_MARKER}测试负责人",
            "name_en": "Local Table UAT Owner",
            "employment_type": "正式",
            "work_location": "本地隔离环境",
            "department_id": department.id,
            "position_id": position.id,
            "status": "在岗",
            "skills": ["宽表验收", "固定列验收"],
        },
    )
    db.flush()
    domain = _upsert(
        db,
        BusinessDomain,
        {"code": "uat_table_domain"},
        {
            "name": f"{UAT_MARKER}数字化业务域",
            "description": "仅用于本地表格显示与滚动验收",
            "owner_id": member.id,
            "business_bdo_id": member.id,
            "sort": 9900,
            "active": True,
        },
    )
    catalog = _upsert(
        db,
        ServiceCatalog,
        {"code": "SC-UAT-TABLE"},
        {
            "name": f"{UAT_MARKER}本地服务目录",
            "tier": "silver",
            "description": "合成长文本与多状态数据",
            "sort": 9900,
            "status": "上架",
        },
    )
    db.flush()
    service_item = _upsert(
        db,
        ServiceItem,
        {"item_code": "SI-UAT-TABLE"},
        {
            "name": f"{UAT_MARKER}跨系统访问与账号权限支持",
            "catalog_id": catalog.id,
            "service_type": "日常运维",
            "owner": member.id,
            "description": "用于验证服务项、提交人和当前节点等宽列的显示边界",
            "target_audience_mode": "all",
            "target_audience_refs": [],
            "status": "上架",
        },
    )

    ci_rows: list[Ci] = []
    ci_categories = ("应用", "服务器", "云资源", "网络", "安全")
    for index in range(1, 31):
        ci = _upsert(
            db,
            Ci,
            {"ci_code": f"CI-UAT-TABLE-{index:03d}"},
            {
                "name": f"{UAT_MARKER}{index:02d}-跨区域订单履约与库存协同平台组件",
                "category": ci_categories[(index - 1) % len(ci_categories)],
                "status": ("运行中", "维护中", "已下线")[index % 3],
                "owner": member.id,
                "product_manager_id": member.id,
                "environment": ("生产", "测试", "开发")[index % 3],
                "business_owner": "本地测试业务负责人",
                "description": "合成配置项：验证长名称、负责人、供应商与固定操作列",
                "launch_date": today - timedelta(days=index * 3),
                "attrs": {"地址": f"10.250.{index // 255}.{index % 255}", "规格": "8C32G"},
            },
        )
        ci_rows.append(ci)
    db.flush()

    ticket_statuses = ("new", "processing", "resolved", "closed")
    for index in range(1, 71):
        ticket_type = "service_request" if index <= 35 else "incident"
        _upsert(
            db,
            Ticket,
            {"ticket_code": f"TK-UAT-TABLE-{index:04d}"},
            {
                "title": f"{UAT_MARKER}{index:03d}-跨区域办公网络、共享账号与生产系统访问异常需要协同处理",
                "ticket_type": ticket_type,
                "priority": ("P1", "P2", "P3", "P4")[index % 4],
                "description": "合成工单：用于验证长标题、多状态、SLA、当前节点和动态操作列宽。",
                "service_item_id": service_item.id,
                "assignee": member.id if index % 5 else None,
                "ci_id": ci_rows[index % len(ci_rows)].id,
                "status": ticket_statuses[index % len(ticket_statuses)],
                "submitter_name": f"本地测试提交人{index % 7 + 1}",
                "submitter_dept": "数字化与流程效率组",
                "service_line": catalog.name,
                "submitted_at": now - timedelta(minutes=index * 11),
                "first_response_at": now - timedelta(minutes=index * 7),
                "resolved_at": now - timedelta(minutes=index) if index % 4 in {2, 3} else None,
                "closed_at": now - timedelta(minutes=index) if index % 4 == 3 else None,
                "sla_response_min": 60,
                "sla_resolution_hours": 8,
                "actual_response_min": float(index % 50 + 1),
                "actual_resolution_hours": float(index % 10 + 1),
                "sla_response_met": index % 5 != 0,
                "sla_resolution_met": index % 6 != 0,
                "sla_warned": index % 9 == 0,
            },
        )

    portfolio = _upsert(
        db,
        Portfolio,
        {"name": f"{UAT_MARKER}年度数字化项目组合"},
        {"owner_id": member.id, "year": str(today.year), "description": "本地项目宽表验收", "sort": 9900},
    )
    db.flush()
    project_rows: list[Project] = []
    project_statuses = ("planning", "active", "paused", "completed", "closed")
    for index in range(1, 26):
        status = project_statuses[index % len(project_statuses)]
        project = _upsert(
            db,
            Project,
            {"project_code": f"PJ-UAT-TABLE-{index:03d}"},
            {
                "name": f"{UAT_MARKER}{index:02d}-跨组织主数据治理与供应链协同能力建设项目",
                "pm": member.id,
                "status": status,
                "planned_start": today - timedelta(days=30 + index),
                "planned_end": today + timedelta(days=60 + index),
                "actual_start": today - timedelta(days=20) if status != "planning" else None,
                "actual_end": today - timedelta(days=1) if status in {"completed", "closed"} else None,
                "portfolio_id": portfolio.id,
                "service_item_id": service_item.id,
                "budget_10k": float(50 + index * 3),
                "description": "合成项目：验证项目经理、状态、健康度、进度、日期和操作列。",
                "latest_update": "已完成跨部门方案评审，正在推进接口联调与批量数据校验。",
            },
        )
        project_rows.append(project)
    db.flush()

    first_project = project_rows[0]
    wbs_rows: list[WbsTask] = []
    for group in range(1, 6):
        root = _upsert(
            db,
            WbsTask,
            {"project_id": first_project.id, "wbs_code": str(group)},
            {
                "parent_task_id": None,
                "stage": f"{group}.实施阶段",
                "name": f"{UAT_MARKER}阶段{group}总体交付包",
                "wbs_dict": "包含方案、开发、测试、上线与验收证据；不包含生产数据复制。",
                "deliverable": "评审记录、可运行版本、测试报告和验收清单",
                "assignee": member.id,
                "start_date": today - timedelta(days=20 - group),
                "end_date": today + timedelta(days=group * 10),
                "progress": group * 10,
                "sort": group * 100,
                "predecessor_ids": [],
            },
        )
        db.flush()
        wbs_rows.append(root)
        for child in range(1, 15):
            progress = 100 if child <= 2 else (child * 7) % 100
            task = _upsert(
                db,
                WbsTask,
                {"project_id": first_project.id, "wbs_code": f"{group}.{child}"},
                {
                    "parent_task_id": root.id,
                    "stage": f"{group}.实施阶段",
                    "name": f"{UAT_MARKER}工作包{group}.{child}-长名称交付物与跨团队协作验证",
                    "wbs_dict": "验证层级、选择框、行数裁剪、列设置、横向滚动和固定操作列。",
                    "deliverable": "可核验交付物与验收标准",
                    "assignee": member.id,
                    "start_date": today - timedelta(days=child),
                    "end_date": today + timedelta(days=child),
                    "actual_start": today - timedelta(days=child) if progress else None,
                    "actual_end": today - timedelta(days=1) if progress == 100 else None,
                    "progress": progress,
                    "completed_at": now - timedelta(days=1) if progress == 100 else None,
                    "sort": group * 100 + child,
                    "predecessor_ids": [],
                },
            )
            wbs_rows.append(task)
    db.flush()

    requirement_rows: list[Requirement] = []
    for index in range(1, 21):
        requirement = _upsert(
            db,
            Requirement,
            {"requirement_code": f"RQ-UAT-TABLE-{index:03d}"},
            {
                "title": f"{UAT_MARKER}{index:02d}-订单履约异常自动识别与跨系统协同处理需求",
                "req_type": ("业务", "功能", "数据", "集成")[index % 4],
                "business_domain_id": domain.id,
                "description": "合成需求：用于需求活动任务宽表、加权分和关联需求列验收。",
                "source": "业务部门",
                "requester_name": "本地业务用户",
                "owner": member.id,
                "target_date": today + timedelta(days=30 + index),
                "status": "implementing" if index % 2 else "analyzing",
                "score_d1_strategy": 4,
                "score_d2_value": 5,
                "score_d3_tech": 4,
                "score_d4_org": 3,
                "score_d5_risk": 2,
                "score_d6_speed": 4,
                "project_id": first_project.id,
                "registered_at": now - timedelta(days=index),
                "implementing_at": now - timedelta(days=max(1, index // 2)),
            },
        )
        requirement_rows.append(requirement)
    db.flush()
    for index in range(1, 56):
        _upsert(
            db,
            RequirementTask,
            {"task_code": f"RT-UAT-TABLE-{index:04d}"},
            {
                "requirement_id": requirement_rows[index % len(requirement_rows)].id,
                "registrar": member.id,
                "name": f"{UAT_MARKER}{index:03d}-接口字段映射、异常补偿与回归验证任务",
                "description": "长描述用于验证任务描述、负责人、关联需求与操作列不会重叠。",
                "assignee": member.id,
                "plan_date": today + timedelta(days=index % 20),
                "plan_effort": float(index % 8 + 1),
                "actual_effort": float(index % 5) if index % 3 == 0 else None,
                "status": ("待处理", "进行中", "已完成")[index % 3],
                "done_at": now - timedelta(days=1) if index % 3 == 2 else None,
            },
        )

    for index in range(1, 56):
        status = ("登记", "排期", "执行", "暂停", "关闭", "中止")[index % 6]
        _upsert(
            db,
            WorkTask,
            {"task_code": f"WT-UAT-TABLE-{index:04d}"},
            {
                "title": f"{UAT_MARKER}{index:03d}-跨团队迁移计划、验证与知识交接任务",
                "description": "合成委派任务：验证长文本、状态操作组合、批量选择和底部滚动条。",
                "task_type": ("其他", "跨团队支援", "技术研究")[index % 3],
                "source_type": "manual",
                "registrar": member.id,
                "assignee": member.id if index % 4 else None,
                "priority": ("P1", "P2", "P3", "P4")[index % 4],
                "plan_start": today - timedelta(days=index % 10),
                "plan_date": today + timedelta(days=index % 20),
                "plan_effort": float(index % 8 + 1),
                "actual_effort": float(index % 6),
                "status": status,
                "performance_bucket": "role_result",
                "pause_reason": "等待外部依赖" if status == "暂停" else None,
                "abort_reason": "本地负向状态样本" if status == "中止" else None,
                "completion_note": "本地验收完成" if status == "关闭" else None,
                "closed_at": now - timedelta(days=1) if status == "关闭" else None,
            },
        )

    for index in range(1, 56):
        _upsert(
            db,
            ProjectDevelopmentTask,
            {"task_code": f"PT-UAT-TABLE-{index:04d}"},
            {
                "project_id": project_rows[index % len(project_rows)].id,
                "wbs_task_id": wbs_rows[index % len(wbs_rows)].id,
                "title": f"{UAT_MARKER}{index:03d}-主数据同步接口与异常补偿机制开发任务",
                "description": "验证项目、WBS、版本、环境、状态、进度与操作列。",
                "acceptance_criteria": "接口幂等、失败可重试、日志脱敏、回归通过",
                "task_type": "开发",
                "registrar": member.id,
                "assignee": member.id,
                "priority": ("P1", "P2", "P3", "P4")[index % 4],
                "environment": ("开发", "测试", "预生产")[index % 3],
                "version": f"uat-{index // 10}.{index % 10}",
                "plan_start": today - timedelta(days=index % 10),
                "plan_date": today + timedelta(days=index % 20),
                "plan_effort": float(index % 10 + 1),
                "actual_effort": float(index % 7),
                "status": ("待处理", "进行中", "已完成")[index % 3],
                "completion_note": "本地合成完成记录" if index % 3 == 2 else None,
                "done_at": now - timedelta(days=1) if index % 3 == 2 else None,
            },
        )

    bug_rows: list[Bug] = []
    bug_statuses = ("registered", "confirmed", "fixing", "resolved", "closed", "rejected")
    for index in range(1, 31):
        bug = _upsert(
            db,
            Bug,
            {"bug_code": f"BG-UAT-TABLE-{index:04d}"},
            {
                "title": f"{UAT_MARKER}{index:03d}-批量处理页面在窄屏下出现字段遮挡与操作区重叠",
                "description": "合成 Bug：覆盖确认、修复、验证、关闭与重开状态按钮。",
                "priority": ("P1", "P2", "P3", "P4")[index % 4],
                "status": bug_statuses[index % len(bug_statuses)],
                "ci_id": ci_rows[index % len(ci_rows)].id,
                "product_manager_id": member.id,
                "dev_leader_id": member.id,
                "reproduction": "打开宽表并横向拖动到底部，检查固定列边界。",
                "expected_result": "固定列完全遮挡滚动内容，操作区无多余留白。",
                "actual_result": "本地合成的历史问题描述。",
                "environment": "本地 Docker 18180",
            },
        )
        bug_rows.append(bug)
    db.flush()
    for index, bug in enumerate(bug_rows, start=1):
        _upsert(
            db,
            BugFixTask,
            {"task_code": f"BF-UAT-TABLE-{index:04d}"},
            {
                "bug_id": bug.id,
                "name": f"{UAT_MARKER}{index:03d}-修复表格固定列与滚动条",
                "task_type": "开发",
                "description": "本地合成 Bug 修复任务",
                "assignee": member.id,
                "plan_start": today - timedelta(days=2),
                "plan_date": today + timedelta(days=3),
                "plan_effort": 2.0,
                "actual_effort": 1.0,
                "status": ("登记", "排期", "执行", "暂停", "关闭")[index % 5],
            },
        )

    db.commit()
    return {
        "tickets": 70,
        "configuration_items": 30,
        "projects": 25,
        "wbs_tasks": 75,
        "requirements": 20,
        "requirement_tasks": 55,
        "delegated_tasks": 55,
        "project_development_tasks": 55,
        "bugs": 30,
        "bug_fix_tasks": 30,
    }


def cleanup_table_uat(db: Session) -> dict[str, int]:
    """Soft-delete only rows carrying the dedicated local UAT identifiers."""

    assert_local_uat_database(str(db.get_bind().url))
    targets = (
        (BugFixTask, BugFixTask.task_code.like("BF-UAT-TABLE-%")),
        (Bug, Bug.bug_code.like("BG-UAT-TABLE-%")),
        (ProjectDevelopmentTask, ProjectDevelopmentTask.task_code.like("PT-UAT-TABLE-%")),
        (WorkTask, WorkTask.task_code.like("WT-UAT-TABLE-%")),
        (RequirementTask, RequirementTask.task_code.like("RT-UAT-TABLE-%")),
        (Requirement, Requirement.requirement_code.like("RQ-UAT-TABLE-%")),
        (WbsTask, WbsTask.name.like(f"{UAT_MARKER}%")),
        (Project, Project.project_code.like("PJ-UAT-TABLE-%")),
        (Portfolio, Portfolio.name == f"{UAT_MARKER}年度数字化项目组合"),
        (Ticket, Ticket.ticket_code.like("TK-UAT-TABLE-%")),
        (Ci, Ci.ci_code.like("CI-UAT-TABLE-%")),
        (ServiceItem, ServiceItem.item_code == "SI-UAT-TABLE"),
        (ServiceCatalog, ServiceCatalog.code == "SC-UAT-TABLE"),
        (BusinessDomain, BusinessDomain.code == "uat_table_domain"),
        (OrgMember, OrgMember.employee_no == "UAT-TABLE-001"),
        (Position, Position.position_code == "UAT-TABLE-DEV"),
        (Department, Department.code == "uat_table_it"),
    )
    result: dict[str, int] = {}
    for model, predicate in targets:
        count = db.query(model).filter(predicate, model.is_deleted.is_(False)).update(
            {model.is_deleted: True}, synchronize_session=False
        )
        result[model.__tablename__] = count
    db.commit()
    return result
