"""M82：任务管理域的新增模型必须可创建，且不影响既有需求任务。"""

from sqlalchemy import inspect

from app.db import Base, engine
from app.models import Bug, BugFixTask, Ci, Requirement, RequirementTask, WorkTask


def test_task_management_models_are_registered_without_replacing_requirement_task():
    tables = set(Base.metadata.tables)

    assert {"bug", "bug_fix_task", "work_task", "requirement_task"} <= tables
    assert Bug.__tablename__ == "bug"
    assert BugFixTask.__tablename__ == "bug_fix_task"
    assert WorkTask.__tablename__ == "work_task"
    assert RequirementTask.__tablename__ == "requirement_task"


def test_ci_product_manager_is_nullable_for_existing_configuration_items():
    column = next(c for c in Ci.__table__.columns if c.name == "product_manager_id")
    assert column.nullable is True


def test_requirement_implementation_route_is_nullable_for_legacy_records():
    column = next(c for c in Requirement.__table__.columns if c.name == "implementation_route")
    assert column.nullable is True


def test_existing_database_schema_can_keep_requirement_task_and_add_new_tables():
    Base.metadata.create_all(bind=engine)
    names = set(inspect(engine).get_table_names())

    assert "requirement_task" in names
    assert {"bug", "bug_fix_task", "work_task"} <= names
