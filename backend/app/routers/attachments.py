import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.core.glid import new_glid
from app.db import get_db
from app.deps import get_current_user
from app.models import Attachment, AuthUser, Bug, Requirement, Ticket
from app.schemas.common import ok
from app.services import process_engine
from app.services.permissions import has_perm
from app.services.requirement_access import can_view_requirement

router = APIRouter(prefix="/api/attachments", tags=["support"])

MAX_SIZE = 50 * 1024 * 1024  # 50MB
MAX_TICKET_ATTACHMENTS = 10
TICKET_DRAFT_ENTITY_TYPE = "ticket_draft"
REQUIREMENT_DRAFT_ENTITY_TYPE = "requirement_draft"
TICKET_ATTACHMENT_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv",
}
TICKET_DRAFT_TTL = timedelta(hours=24)
DRAFT_ENTITY_TYPES = {TICKET_DRAFT_ENTITY_TYPE, REQUIREMENT_DRAFT_ENTITY_TYPE}


def _require_bug_attachment_access(db: Session, user: AuthUser, bug_id: str, *, mutate: bool) -> None:
    """Keep Bug evidence inside the same permission boundary as the Bug record.

    Generic attachments predate task management and are still used by several
    legacy entities.  Bug evidence is different: an upload changes the Bug's
    evidence set, so it must respect the workflow correction window instead of
    allowing every authenticated account to append a file.
    """
    bug = db.get(Bug, bug_id)
    if not bug or bug.is_deleted:
        raise AppError("NOT_FOUND", "Bug 不存在", 404)
    if mutate:
        process_engine.require_workflow_edit(db, user, "bug", bug.id, "task_bug")
        return
    if not has_perm(db, user, "task_bug", "view"):
        raise AppError("FORBIDDEN", "没有查看 Bug 附件的权限", 403)


def _ticket_entity_type(ticket: Ticket) -> str:
    return "ticket_change" if ticket.ticket_type == "change" else "ticket"


def _require_ticket_attachment_access(db: Session, user: AuthUser, ticket_id: str, *, mutate: bool) -> Ticket:
    """附件与服务请求本身保持同一账号、数据范围和流程编辑边界。"""
    from app.core.rbac import BDO, REQUESTER
    from app.services.permissions import TICKET_TYPE_MODULE
    from app.services.rbac import effective_roles

    ticket = db.get(Ticket, ticket_id)
    if not ticket or ticket.is_deleted:
        raise AppError("NOT_FOUND", "工单不存在", 404)
    module = TICKET_TYPE_MODULE.get(ticket.ticket_type, "ticket_sr")
    if not has_perm(db, user, module, "view"):
        raise AppError("FORBIDDEN", "没有查看该工单附件的权限", 403)
    roles = effective_roles(db, user)
    if roles and roles.issubset({REQUESTER, BDO}) and ticket.submitter != user.id:
        raise AppError("FORBIDDEN", "没有查看该工单附件的权限", 403)
    if mutate:
        process_engine.require_workflow_edit(db, user, _ticket_entity_type(ticket), ticket.id, module)
    return ticket


def _require_requirement_attachment_access(
    db: Session, user: AuthUser, requirement_id: str, *, mutate: bool
) -> Requirement:
    """需求附件沿用需求单本身的查看范围和流程回改窗口。"""
    requirement = db.get(Requirement, requirement_id)
    if not requirement or requirement.is_deleted:
        raise AppError("NOT_FOUND", "需求不存在", 404)
    if not has_perm(db, user, "requirements", "view"):
        raise AppError("FORBIDDEN", "没有查看该需求附件的权限", 403)
    if not can_view_requirement(db, user, requirement):
        raise AppError("FORBIDDEN", "没有查看该需求附件的权限", 403)
    if mutate:
        process_engine.require_workflow_edit(db, user, "requirement", requirement.id, "requirements")
    return requirement


def _attachment_row(att: Attachment) -> dict:
    return {"id": att.id, "filename": att.filename, "size": att.size, "created_at": att.created_at}


def _safe_filename(file: UploadFile) -> str:
    return os.path.basename(file.filename or "attachment")


def _remove_storage_file(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        # 已软删除的附件元数据仍是审计事实；物理文件清理失败不应回滚业务操作。
        pass


def _purge_expired_drafts(db: Session, draft_entity_type: str) -> None:
    """清理过期的创建草稿，避免取消登记后长期占用 RWO 附件卷。"""
    cutoff = datetime.now() - TICKET_DRAFT_TTL
    expired = (
        db.query(Attachment)
        .filter(
            Attachment.entity_type == draft_entity_type,
            Attachment.created_at < cutoff,
            Attachment.is_deleted.is_(False),
        )
        .all()
    )
    for attachment in expired:
        attachment.is_deleted = True
        _remove_storage_file(attachment.storage_path)
    if expired:
        db.commit()


@router.post("")
async def upload(
    file: UploadFile,
    entity_type: str,
    entity_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    # ``*_draft`` 是创建前的受控暂存态；必须使用专用端点，不能绕过
    # 上传人、数量、文件类型及过期策略。
    if entity_type in DRAFT_ENTITY_TYPES:
        raise AppError("FORBIDDEN", "请使用单据临时附件接口", 403)
    if entity_type == "bug":
        _require_bug_attachment_access(db, user, entity_id, mutate=True)
    elif entity_type == "ticket":
        _require_ticket_attachment_access(db, user, entity_id, mutate=True)
    elif entity_type == "requirement":
        _require_requirement_attachment_access(db, user, entity_id, mutate=True)
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise AppError("FILE_TOO_LARGE", "附件不能超过 50MB")
    os.makedirs(settings.upload_dir, exist_ok=True)
    filename = _safe_filename(file)
    if entity_type in {"ticket", "requirement"}:
        suffix = os.path.splitext(filename)[1].lower()
        if suffix not in TICKET_ATTACHMENT_SUFFIXES:
            raise AppError("ATTACHMENT_TYPE_UNSUPPORTED", "仅支持图片、PDF 和常见办公文档附件", 422)
        if not content:
            raise AppError("ATTACHMENT_EMPTY", "附件不能为空", 422)
        attached_count = (
            db.query(Attachment)
            .filter(
                Attachment.entity_type == entity_type,
                Attachment.entity_id == entity_id,
                Attachment.is_deleted.is_(False),
            )
            .count()
        )
        if attached_count >= MAX_TICKET_ATTACHMENTS:
            label = "服务请求" if entity_type == "ticket" else "需求"
            raise AppError("ATTACHMENT_LIMIT_EXCEEDED", f"单张{label}最多上传 {MAX_TICKET_ATTACHMENTS} 个附件")
    ext = os.path.splitext(filename)[1][:16]
    storage_name = f"{new_glid()}{ext}"
    path = os.path.join(settings.upload_dir, storage_name)
    with open(path, "wb") as f:
        f.write(content)
    att = Attachment(
        entity_type=entity_type,
        entity_id=entity_id,
        filename=filename or storage_name,
        storage_path=path,
        size=len(content),
        uploaded_by=user.id,
    )
    db.add(att)
    db.commit()
    return ok(_attachment_row(att))


async def _upload_controlled_draft(
    file: UploadFile,
    db: Session,
    user: AuthUser,
    *,
    draft_entity_type: str,
    module: str,
    document_label: str,
):
    """创建前附件的统一受控暂存：上传人本人、数量、类型和过期策略不可绕过。"""
    if not has_perm(db, user, module, "create"):
        raise AppError("FORBIDDEN", f"没有创建{document_label}附件的权限", 403)
    _purge_expired_drafts(db, draft_entity_type)
    pending_count = (
        db.query(Attachment)
        .filter(
            Attachment.entity_type == draft_entity_type,
            Attachment.entity_id == user.id,
            Attachment.uploaded_by == user.id,
            Attachment.is_deleted.is_(False),
        )
        .count()
    )
    if pending_count >= MAX_TICKET_ATTACHMENTS:
        raise AppError("ATTACHMENT_LIMIT_EXCEEDED", f"单张{document_label}最多上传 {MAX_TICKET_ATTACHMENTS} 个附件")
    filename = _safe_filename(file)
    suffix = os.path.splitext(filename)[1].lower()
    if suffix not in TICKET_ATTACHMENT_SUFFIXES:
        raise AppError("ATTACHMENT_TYPE_UNSUPPORTED", "仅支持图片、PDF 和常见办公文档附件", 422)
    content = await file.read()
    if not content:
        raise AppError("ATTACHMENT_EMPTY", "附件不能为空", 422)
    if len(content) > MAX_SIZE:
        raise AppError("FILE_TOO_LARGE", "附件不能超过 50MB")
    os.makedirs(settings.upload_dir, exist_ok=True)
    storage_name = f"{new_glid()}{suffix}"
    path = os.path.join(settings.upload_dir, storage_name)
    with open(path, "wb") as handle:
        handle.write(content)
    attachment = Attachment(
        entity_type=draft_entity_type,
        entity_id=user.id,
        filename=filename,
        storage_path=path,
        size=len(content),
        uploaded_by=user.id,
    )
    db.add(attachment)
    db.commit()
    return ok(_attachment_row(attachment))


@router.post("/ticket-drafts")
async def upload_ticket_draft(
    file: UploadFile,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    """服务请求提交前的受控临时附件；只能由本人在随后建单时绑定。"""
    return await _upload_controlled_draft(
        file, db, user,
        draft_entity_type=TICKET_DRAFT_ENTITY_TYPE,
        module="ticket_sr",
        document_label="服务请求",
    )


@router.post("/requirement-drafts")
async def upload_requirement_draft(
    file: UploadFile,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    """需求登记前的受控临时附件；提交时由需求领域服务原子绑定。"""
    return await _upload_controlled_draft(
        file, db, user,
        draft_entity_type=REQUIREMENT_DRAFT_ENTITY_TYPE,
        module="requirements",
        document_label="需求",
    )


def _delete_controlled_draft(db: Session, user: AuthUser, attachment_id: str, draft_entity_type: str):
    attachment = db.get(Attachment, attachment_id)
    if (
        not attachment
        or attachment.is_deleted
        or attachment.entity_type != draft_entity_type
        or attachment.entity_id != user.id
        or attachment.uploaded_by != user.id
    ):
        raise AppError("NOT_FOUND", "临时附件不存在", 404)
    attachment.is_deleted = True
    db.commit()
    _remove_storage_file(attachment.storage_path)
    return ok({"id": attachment_id})


@router.delete("/ticket-drafts/{attachment_id}")
def delete_ticket_draft(
    attachment_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return _delete_controlled_draft(db, user, attachment_id, TICKET_DRAFT_ENTITY_TYPE)


@router.delete("/requirement-drafts/{attachment_id}")
def delete_requirement_draft(
    attachment_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    return _delete_controlled_draft(db, user, attachment_id, REQUIREMENT_DRAFT_ENTITY_TYPE)


@router.get("")
def list_attachments(
    entity_type: str,
    entity_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
):
    # 建单前临时附件只能被创建接口绑定或由本人取消。它们既不是业务单据
    # 的证据，也不应通过猜测 entity_id 被其他账号读取。
    if entity_type in DRAFT_ENTITY_TYPES:
        raise AppError("FORBIDDEN", "临时附件不能通过附件清单读取", 403)
    if entity_type == "bug":
        _require_bug_attachment_access(db, user, entity_id, mutate=False)
    elif entity_type == "ticket":
        _require_ticket_attachment_access(db, user, entity_id, mutate=False)
    elif entity_type == "requirement":
        _require_requirement_attachment_access(db, user, entity_id, mutate=False)
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
        [_attachment_row(a) for a in items],
        total=len(items),
    )


@router.get("/{attachment_id}/download")
def download(attachment_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    att = db.get(Attachment, attachment_id)
    if not att or att.is_deleted or not os.path.exists(att.storage_path):
        raise AppError("NOT_FOUND", "附件不存在", 404)
    if att.entity_type in DRAFT_ENTITY_TYPES:
        raise AppError("FORBIDDEN", "临时附件不能下载", 403)
    if att.entity_type == "bug":
        _require_bug_attachment_access(db, user, att.entity_id, mutate=False)
    elif att.entity_type == "ticket":
        _require_ticket_attachment_access(db, user, att.entity_id, mutate=False)
    elif att.entity_type == "requirement":
        _require_requirement_attachment_access(db, user, att.entity_id, mutate=False)
    return FileResponse(att.storage_path, filename=att.filename)
