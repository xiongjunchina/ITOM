"""流程任务操作 + 定义只读（完整管理页在 M6）。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models import AuthUser, ProcessDefinition
from app.schemas.common import ok
from app.services import process_engine
from app.services.audit import audit

router = APIRouter(tags=["process"])


class CompleteIn(BaseModel):
    comment: str = ""


class ReassignIn(BaseModel):
    assignee: str


@router.post("/api/process-tasks/{task_id}/complete")
def complete(task_id: str, body: CompleteIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    instance = process_engine.complete_task(db, task_id, user, body.comment)
    audit(db, "process_task", task_id, "complete", user, {"comment": body.comment})
    db.commit()
    return ok({"instance_id": instance.id, "status": instance.status, "current_step_seq": instance.current_step_seq})


@router.post("/api/process-tasks/{task_id}/reassign")
def reassign(task_id: str, body: ReassignIn, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    task = process_engine.reassign_task(db, task_id, body.assignee)
    audit(db, "process_task", task_id, "reassign", user, {"assignee": body.assignee})
    db.commit()
    return ok({"id": task.id, "assignee": task.assignee})


@router.get("/api/admin/process-definitions")
def list_definitions(db: Session = Depends(get_db), _=Depends(require_roles())):
    rows = db.query(ProcessDefinition).filter(ProcessDefinition.is_deleted.is_(False)).all()
    return ok(
        [
            {
                "id": d.id, "code": d.code, "name": d.name, "entity_type": d.entity_type,
                "trigger_condition": d.trigger_condition, "active": d.active,
                "steps": [
                    {"seq": s.seq, "name": s.name, "default_role": s.default_role,
                     "autonomy_level": s.autonomy_level, "sla_hours": s.sla_hours}
                    for s in d.steps
                ],
            }
            for d in rows
        ],
        total=len(rows),
    )
