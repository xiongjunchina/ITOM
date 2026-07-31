"""跨域单据关联的只读接口（创建由各领域“创建并关联”路径在同一事务内完成）。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import AuthUser
from app.schemas.common import ok
from app.services.record_relations import list_visible_relations

router = APIRouter(prefix="/api/records", tags=["record-relations"])


@router.get("/{entity_type}/{entity_id}/relations")
def get_record_relations(
    entity_type: str,
    entity_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return ok(list_visible_relations(db, entity_type=entity_type, entity_id=entity_id, actor=user))
