from app.db import SessionLocal
from app.models import ProcessDefinition


def test_bug_flow_is_seeded_with_five_nodes(client):
    with SessionLocal() as db:
        definition = db.query(ProcessDefinition).filter_by(code="bug_flow").one()
        steps = list(definition.steps)

    assert definition.entity_type == "bug"
    assert [step.name for step in steps] == [
        "登记 Bug",
        "Bug 确认",
        "生成修复任务",
        "开发修复",
        "验证关闭",
    ]
    assert [step.node_type for step in steps] == [
        "processing",
        "approval",
        "processing",
        "processing",
        "approval",
    ]


def test_bug_flow_assigns_creation_and_development_to_development_leader(client):
    with SessionLocal() as db:
        definition = db.query(ProcessDefinition).filter_by(code="bug_flow").one()
        steps = list(definition.steps)

    assert steps[2].default_role == "it_dev_leader"
    assert steps[3].default_role == "it_dev_leader"
