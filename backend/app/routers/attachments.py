import os

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.core.glid import new_glid
from app.db import get_db
from app.deps import get_current_user
from app.models import Attachment, AuthUser
from app.schemas.common import ok

router = APIRouter(prefix="/api/attachments", tags=["support"])

MAX_SIZE = 50 * 1024 * 1024  # 50MB


@router.post("")
async def upload(
    file: UploadFile,
    entity_type: str,
    entity_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise AppError("FILE_TOO_LARGE", "附件不能超过 50MB")
    os.makedirs(settings.upload_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1][:16]
    storage_name = f"{new_glid()}{ext}"
    path = os.path.join(settings.upload_dir, storage_name)
    with open(path, "wb") as f:
        f.write(content)
    att = Attachment(
        entity_type=entity_type,
        entity_id=entity_id,
        filename=file.filename or storage_name,
        storage_path=path,
        size=len(content),
        uploaded_by=user.id,
    )
    db.add(att)
    db.commit()
    return ok({"id": att.id, "filename": att.filename, "size": att.size})


@router.get("")
def list_attachments(
    entity_type: str,
    entity_id: str,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(get_current_user),
):
    items = (
        db.query(Attachment)
        .filter(
            Attachment.entity_type == entity_type,
            Attachment.entity_id == entity_id,
            Attachment.is_deleted.is_(False),
        )
        .order_by(Attachment.created_at.desc())
        .all()
    )
    return ok(
        [{"id": a.id, "filename": a.filename, "size": a.size, "created_at": a.created_at} for a in items],
        total=len(items),
    )


@router.get("/{attachment_id}/download")
def download(attachment_id: str, db: Session = Depends(get_db), _: AuthUser = Depends(get_current_user)):
    att = db.get(Attachment, attachment_id)
    if not att or att.is_deleted or not os.path.exists(att.storage_path):
        raise AppError("NOT_FOUND", "附件不存在", 404)
    return FileResponse(att.storage_path, filename=att.filename)
