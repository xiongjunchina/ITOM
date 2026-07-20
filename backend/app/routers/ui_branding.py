import os
from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.core.glid import new_glid
from app.db import get_db
from app.deps import require_perm
from app.models import AuthUser, UiBrandingAsset, UiBrandingVersion
from app.schemas.common import ok
from app.services.audit import audit
from app.services.ui_branding import default_config, merge_defaults

router = APIRouter(tags=["ui-branding"])
ALLOWED_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/x-icon": ".ico", "image/vnd.microsoft.icon": ".ico"}
ALLOWED_KINDS = {"logo_light", "logo_dark", "logo_square", "favicon", "login_background"}
MAX_SIZE = 5 * 1024 * 1024


class BrandingIn(BaseModel):
    config: dict


def _published(db: Session):
    return db.query(UiBrandingVersion).filter(UiBrandingVersion.status == "published", UiBrandingVersion.is_deleted.is_(False)).order_by(UiBrandingVersion.version.desc()).first()


def _draft(db: Session):
    return db.query(UiBrandingVersion).filter(UiBrandingVersion.status == "draft", UiBrandingVersion.is_deleted.is_(False)).order_by(UiBrandingVersion.updated_at.desc()).first()


def _payload(row: UiBrandingVersion | None):
    return {"id": row.id if row else None, "version": row.version if row else 0, "status": row.status if row else "default", "config": merge_defaults(row.config if row else None), "updated_at": row.updated_at if row else None}


@router.get("/api/public/ui-branding")
def public_branding(db: Session = Depends(get_db)):
    return ok(_payload(_published(db)))


@router.get("/api/public/ui-branding/assets/{asset_id}")
def public_asset(asset_id: str, db: Session = Depends(get_db)):
    asset = db.get(UiBrandingAsset, asset_id)
    if not asset or asset.is_deleted or not os.path.isfile(asset.storage_path):
        raise AppError("NOT_FOUND", "品牌资源不存在", 404)
    return FileResponse(asset.storage_path, media_type=asset.content_type)


@router.get("/api/admin/ui-branding")
def admin_branding(db: Session = Depends(get_db), _: AuthUser = Depends(require_perm("admin_ui_branding", "view"))):
    return ok({"draft": _payload(_draft(db)), "published": _payload(_published(db))})


@router.put("/api/admin/ui-branding/draft")
def save_draft(body: BrandingIn, db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("admin_ui_branding", "edit"))):
    config = merge_defaults(body.config)
    row = _draft(db)
    if row:
        row.config = config
    else:
        row = UiBrandingVersion(version=0, status="draft", config=config)
        db.add(row)
        db.flush()
    audit(db, "ui_branding", row.id, "save_draft", actor, {"sections": list(config)})
    db.commit()
    return ok(_payload(row))


@router.post("/api/admin/ui-branding/assets")
async def upload_asset(kind: str, file: UploadFile, db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("admin_ui_branding", "edit"))):
    if kind not in ALLOWED_KINDS:
        raise AppError("INVALID_ASSET_KIND", "品牌资源类型不支持")
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_TYPES:
        raise AppError("INVALID_FILE_TYPE", "仅支持 PNG、JPEG、WebP 和 ICO 图片")
    content = await file.read(MAX_SIZE + 1)
    if len(content) > MAX_SIZE:
        raise AppError("FILE_TOO_LARGE", "品牌图片不能超过 5MB")
    width = height = None
    try:
        image = Image.open(BytesIO(content)); image.verify()
        width, height = image.size
    except Exception:
        raise AppError("INVALID_IMAGE", "图片内容无效")
    if width > 4096 or height > 4096:
        raise AppError("IMAGE_DIMENSIONS_TOO_LARGE", "图片尺寸不能超过 4096×4096")
    asset_dir = os.path.join(settings.upload_dir, "ui-branding")
    os.makedirs(asset_dir, exist_ok=True)
    asset_id = new_glid(); path = os.path.join(asset_dir, asset_id + ALLOWED_TYPES[content_type])
    with open(path, "wb") as target:
        target.write(content)
    asset = UiBrandingAsset(id=asset_id, kind=kind, filename=file.filename or asset_id, storage_path=path, content_type=content_type, size=len(content), width=width, height=height, uploaded_by=actor.id)
    db.add(asset); audit(db, "ui_branding_asset", asset.id, "upload", actor, {"kind": kind, "size": len(content)}); db.commit()
    return ok({"id": asset.id, "url": f"/api/public/ui-branding/assets/{asset.id}", "width": width, "height": height})


@router.post("/api/admin/ui-branding/publish")
def publish(db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("admin_ui_branding", "edit"))):
    draft = _draft(db)
    if not draft:
        raise AppError("DRAFT_NOT_FOUND", "请先保存草稿")
    latest = _published(db); version = (latest.version if latest else 0) + 1
    row = UiBrandingVersion(version=version, status="published", config=merge_defaults(draft.config), published_by=actor.id, published_at=datetime.now())
    db.add(row); db.flush(); audit(db, "ui_branding", row.id, "publish", actor, {"version": version}); db.commit()
    return ok(_payload(row))


@router.get("/api/admin/ui-branding/history")
def history(db: Session = Depends(get_db), _: AuthUser = Depends(require_perm("admin_ui_branding", "view"))):
    rows = db.query(UiBrandingVersion).filter(UiBrandingVersion.status == "published", UiBrandingVersion.is_deleted.is_(False)).order_by(UiBrandingVersion.version.desc()).all()
    return ok([_payload(row) for row in rows], total=len(rows))


@router.post("/api/admin/ui-branding/rollback/{version}")
def rollback(version: int, db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("admin_ui_branding", "edit"))):
    source = db.query(UiBrandingVersion).filter(UiBrandingVersion.version == version, UiBrandingVersion.status == "published", UiBrandingVersion.is_deleted.is_(False)).first()
    if not source: raise AppError("NOT_FOUND", "配置版本不存在", 404)
    latest = _published(db); row = UiBrandingVersion(version=(latest.version if latest else 0) + 1, status="published", config=merge_defaults(source.config), published_by=actor.id, published_at=datetime.now())
    db.add(row); db.flush(); audit(db, "ui_branding", row.id, "rollback", actor, {"from_version": version}); db.commit()
    return ok(_payload(row))


@router.post("/api/admin/ui-branding/reset")
def reset(db: Session = Depends(get_db), actor: AuthUser = Depends(require_perm("admin_ui_branding", "edit"))):
    row = _draft(db)
    if row: row.config = default_config()
    else: row = UiBrandingVersion(version=0, status="draft", config=default_config()); db.add(row); db.flush()
    audit(db, "ui_branding", row.id, "reset_draft", actor); db.commit(); return ok(_payload(row))
