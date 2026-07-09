"""数据字典 / 状态机配置 / 审计日志（admin）。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.rbac import IS_MGR
from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models import AuditLog, AuthUser, MasterData, WorkflowStatus, WorkflowTransition
from app.schemas.common import ok, paginate
from app.schemas.support import MasterDataCreate, MasterDataUpdate
from app.services.audit import audit

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/master-data")
def list_master_data(
    category: str = "", db: Session = Depends(get_db), _: AuthUser = Depends(get_current_user)
):
    query = db.query(MasterData).filter(MasterData.is_deleted.is_(False))
    if category:
        query = query.filter(MasterData.category == category)
    items = query.order_by(MasterData.category, MasterData.sort).all()
    return ok(
        [
            {
                "id": m.id,
                "category": m.category,
                "code": m.code,
                "name": m.name,
                "sort": m.sort,
                "active": m.active,
            }
            for m in items
        ],
        total=len(items),
    )


@router.post("/master-data")
def create_master_data(body: MasterDataCreate, db: Session = Depends(get_db), actor=Depends(require_roles())):
    dup = (
        db.query(MasterData)
        .filter(MasterData.category == body.category, MasterData.code == body.code, MasterData.is_deleted.is_(False))
        .first()
    )
    if dup:
        raise AppError("DUPLICATE", "该类目下编码已存在")
    item = MasterData(**body.model_dump())
    db.add(item)
    db.flush()
    audit(db, "master_data", item.id, "create", actor, {"category": body.category, "code": body.code})
    db.commit()
    return ok({"id": item.id})


@router.patch("/master-data/{item_id}")
def update_master_data(
    item_id: str, body: MasterDataUpdate, db: Session = Depends(get_db), actor=Depends(require_roles())
):
    item = db.get(MasterData, item_id)
    if not item or item.is_deleted:
        raise AppError("NOT_FOUND", "字典项不存在", 404)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(item, k, v)
    audit(db, "master_data", item.id, "update", actor, data)
    db.commit()
    return ok({"id": item.id})


@router.get("/workflow-config")
def get_workflow_config(entity_type: str = "", db: Session = Depends(get_db), _=Depends(require_roles())):
    sq = db.query(WorkflowStatus).filter(WorkflowStatus.is_deleted.is_(False))
    tq = db.query(WorkflowTransition).filter(WorkflowTransition.is_deleted.is_(False))
    if entity_type:
        sq = sq.filter(WorkflowStatus.entity_type == entity_type)
        tq = tq.filter(WorkflowTransition.entity_type == entity_type)
    return ok(
        {
            "statuses": [
                {
                    "id": s.id,
                    "entity_type": s.entity_type,
                    "code": s.code,
                    "name": s.name,
                    "is_initial": s.is_initial,
                    "is_terminal": s.is_terminal,
                    "sort": s.sort,
                }
                for s in sq.order_by(WorkflowStatus.entity_type, WorkflowStatus.sort)
            ],
            "transitions": [
                {
                    "id": t.id,
                    "entity_type": t.entity_type,
                    "from_code": t.from_code,
                    "to_code": t.to_code,
                    "allowed_roles": t.allowed_roles or [],
                }
                for t in tq
            ],
        }
    )


@router.get("/audit-logs")
def list_audit_logs(
    page: int = 1,
    page_size: int = 20,
    entity_type: str = "",
    db: Session = Depends(get_db),
    _=Depends(require_roles(IS_MGR)),  # 信息安全管理员可查审计
):
    query = db.query(AuditLog)
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    items, total = paginate(query.order_by(AuditLog.created_at.desc()), page, page_size)
    return ok(
        [
            {
                "id": a.id,
                "entity_type": a.entity_type,
                "entity_id": a.entity_id,
                "action": a.action,
                "actor_name": a.actor_name,
                "summary": a.summary,
                "created_at": a.created_at,
            }
            for a in items
        ],
        total=total,
        page=page,
    )
