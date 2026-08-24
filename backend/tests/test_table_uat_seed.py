from unittest.mock import Mock

import pytest

from app.db import SessionLocal
from app.models import Project, RequirementTask, Ticket, WbsTask, WorkTask
from app.services.seed_table_uat import (
    UAT_MARKER,
    assert_local_uat_database,
    cleanup_table_uat,
    seed_table_uat,
)


def test_seed_cli_commits_the_verified_local_session(monkeypatch, capsys):
    from app.scripts import seed_table_uat as cli

    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(cli, "SessionLocal", Mock(return_value=session))
    monkeypatch.setattr(cli, "assert_local_uat_database", Mock())
    monkeypatch.setattr(cli, "seed_table_uat", Mock(return_value={"tickets": 70}))
    monkeypatch.setattr(cli.settings, "database_url", "postgresql://local@db:5432/new_aom")
    monkeypatch.setattr("sys.argv", ["seed_table_uat", "seed", "--confirm-local"])

    assert cli.main() == 0
    session.commit.assert_called_once_with()
    assert '"tickets": 70' in capsys.readouterr().out


def test_local_uat_database_guard_rejects_nonlocal_hosts():
    assert_local_uat_database("sqlite:////tmp/table-uat.db")
    assert_local_uat_database("postgresql+psycopg2://user:password@db:5432/new_aom")
    assert_local_uat_database("postgresql+psycopg2://user:password@127.0.0.1:6432/new_aom")
    with pytest.raises(RuntimeError, match="只允许写入本地"):
        assert_local_uat_database("postgresql+psycopg2://user:password@itom-postgres:5432/new_aom")


def test_seed_and_cleanup_recheck_the_bound_database_before_writing():
    remote = Mock()
    remote.get_bind.return_value.url = "postgresql+psycopg2://user:password@itom-postgres:5432/new_aom"
    with pytest.raises(RuntimeError, match="只允许写入本地"):
        seed_table_uat(remote)
    with pytest.raises(RuntimeError, match="只允许写入本地"):
        cleanup_table_uat(remote)


def test_table_uat_seed_is_idempotent_and_cleanable(client):
    with SessionLocal() as db:
        first = seed_table_uat(db)
        second = seed_table_uat(db)
        assert first == second
        assert first["tickets"] == 70
        assert first["wbs_tasks"] == 75
        assert db.query(Ticket).filter(Ticket.ticket_code.like("TK-UAT-TABLE-%"), Ticket.is_deleted.is_(False)).count() == 70
        assert db.query(Project).filter(Project.project_code.like("PJ-UAT-TABLE-%"), Project.is_deleted.is_(False)).count() == 25
        assert db.query(WbsTask).filter(WbsTask.name.like(f"{UAT_MARKER}%"), WbsTask.is_deleted.is_(False)).count() == 75
        assert db.query(RequirementTask).filter(RequirementTask.task_code.like("RT-UAT-TABLE-%"), RequirementTask.is_deleted.is_(False)).count() == 55
        assert db.query(WorkTask).filter(WorkTask.task_code.like("WT-UAT-TABLE-%"), WorkTask.is_deleted.is_(False)).count() == 55
        assert "跨区域办公网络" in db.query(Ticket).filter(Ticket.ticket_code == "TK-UAT-TABLE-0001").one().title

        removed = cleanup_table_uat(db)
        assert removed["ticket"] == 70
        assert removed["wbs_task"] == 75
        assert db.query(Ticket).filter(Ticket.ticket_code.like("TK-UAT-TABLE-%"), Ticket.is_deleted.is_(False)).count() == 0

        reseeded = seed_table_uat(db)
        assert reseeded == first
        assert db.query(Ticket).filter(Ticket.ticket_code.like("TK-UAT-TABLE-%"), Ticket.is_deleted.is_(False)).count() == 70
