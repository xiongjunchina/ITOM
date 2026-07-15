"""知识库（PRD §5.7）：发布 2 必填、全文检索、有用投票（防重复）。"""
from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.errors import AppError, ensure_not_example
from app.db import get_db
from app.deps import get_current_user, require_perm
from app.events.bus import publish
from app.models import AuthUser, KnowledgeArticle, KnowledgeVote, OrgMember, Ticket
from app.schemas.common import ok, paginate
from app.services.audit import audit
from app.services.codes import gen_code

router = APIRouter(prefix="/api/knowledge", tags=["itsm"])


class ArticleCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    content: str = Field(min_length=1)
    tags: list[str] = []
    linked_ticket_ids: list[str] = []
    status: str = "published"  # published/draft


class ArticleUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    linked_ticket_ids: list[str] | None = None
    status: str | None = None


def _row(a: KnowledgeArticle, brief: bool = True) -> dict:
    row = {
        "id": a.id, "article_code": a.article_code, "title": a.title,
        "tags": a.tags or [], "status": a.status,
        "author_name": a.author_name, "view_count": a.view_count, "helpful_count": a.helpful_count,
        "content_format": a.content_format, "is_example": a.is_example,
        "created_at": a.created_at, "updated_at": a.updated_at,
    }
    if not brief:
        row["content"] = a.content
        row["author"] = a.author
        row["linked_ticket_ids"] = a.linked_ticket_ids or []
        row["source_requirement_id"] = a.source_requirement_id
    return row


@router.get("")
def list_articles(
    page: int = 1, page_size: int = 20, q: str = "", tag: str = "", status: str = "",
    db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user),
):
    query = db.query(KnowledgeArticle).filter(KnowledgeArticle.is_deleted.is_(False))
    # 草稿仅作者本人可见
    query = query.filter(or_(KnowledgeArticle.status == "published", KnowledgeArticle.author == user.id))
    if status:
        query = query.filter(KnowledgeArticle.status == status)
    if q:
        query = query.filter(or_(KnowledgeArticle.title.ilike(f"%{q}%"), KnowledgeArticle.content.ilike(f"%{q}%")))
    items, total = paginate(query.order_by(KnowledgeArticle.is_example.desc(), KnowledgeArticle.updated_at.desc()), page, page_size)
    rows = [_row(a) for a in items]
    if tag:
        rows = [r for r in rows if tag in r["tags"]]
    return ok(rows, total=total, page=page)


@router.post("")
def create_article(body: ArticleCreate, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("knowledge", "create"))):
    person = db.get(OrgMember, user.person_id) if user.person_id else None
    article = KnowledgeArticle(
        **body.model_dump(),
        article_code=gen_code(db, KnowledgeArticle, "article_code", "KB"),
        author=user.id,
        author_name=person.name if person else user.username,
    )
    db.add(article)
    db.flush()
    audit(db, "knowledge_article", article.id, "create", user, {"code": article.article_code})
    if article.status == "published":
        publish(db, "knowledge.published", "knowledge_article", article.id, {})
    db.commit()
    return ok(_row(article, brief=False))


@router.get("/{article_id}")
def get_article(article_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    a = db.get(KnowledgeArticle, article_id)
    if not a or a.is_deleted:
        raise AppError("NOT_FOUND", "文章不存在", 404)
    if a.status == "draft" and a.author != user.id:
        raise AppError("FORBIDDEN", "草稿仅作者可见", 403)
    a.view_count = (a.view_count or 0) + 1
    db.commit()
    detail = _row(a, brief=False)
    detail["voted"] = bool(
        db.query(KnowledgeVote).filter_by(article_id=a.id, person=user.id).filter(KnowledgeVote.is_deleted.is_(False)).first()
    )
    if a.linked_ticket_ids:
        tickets = db.query(Ticket).filter(Ticket.id.in_(a.linked_ticket_ids)).all()
        detail["linked_tickets"] = [{"id": t.id, "ticket_code": t.ticket_code, "title": t.title} for t in tickets]
    else:
        detail["linked_tickets"] = []
    return ok(detail)


@router.patch("/{article_id}")
def update_article(article_id: str, body: ArticleUpdate, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("knowledge", "edit"))):
    a = db.get(KnowledgeArticle, article_id)
    if not a or a.is_deleted:
        raise AppError("NOT_FOUND", "文章不存在", 404)
    ensure_not_example(a)
    from app.core.rbac import ADMIN, CIO

    from app.services.rbac import effective_roles

    held = effective_roles(db, user)
    if a.author != user.id and not held & {ADMIN, CIO}:
        raise AppError("FORBIDDEN", "仅作者或负责人可编辑", 403)
    data = body.model_dump(exclude_unset=True)
    was_draft = a.status == "draft"
    for k, v in data.items():
        setattr(a, k, v)
    if was_draft and a.status == "published":
        publish(db, "knowledge.published", "knowledge_article", a.id, {})
    audit(db, "knowledge_article", a.id, "update", user, {"fields": list(data.keys())})
    db.commit()
    return ok(_row(a, brief=False))


@router.delete("/{article_id}")
def delete_article(article_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("knowledge", "delete"))):
    """删除知识文章（M21，软删；delete 权限默认仅 admin）。"""
    a = db.get(KnowledgeArticle, article_id)
    if not a or a.is_deleted:
        raise AppError("NOT_FOUND", "文章不存在", 404)
    ensure_not_example(a)
    a.is_deleted = True
    audit(db, "knowledge_article", a.id, "delete", actor, {"code": a.article_code, "title": a.title})
    db.commit()
    return ok({"id": a.id})


@router.post("/import")
async def import_document(
    file: UploadFile, db: Session = Depends(get_db), user: AuthUser = Depends(require_perm("knowledge", "create"))
):
    """word/markdown/html/txt 导入为知识草稿，供审阅后发布。"""
    from fastapi import UploadFile as _UF  # noqa: F401  (类型仅用于签名)
    from app.services.doc_import import convert_document

    content = await file.read()
    try:
        doc = convert_document(file.filename or "", content)
    except ValueError as e:
        raise AppError("IMPORT_FAILED", str(e))
    person = db.get(OrgMember, user.person_id) if user.person_id else None
    article = KnowledgeArticle(
        title=doc["title"], content=doc["content"], content_format=doc["content_format"],
        status="draft", tags=["导入"],
        article_code=gen_code(db, KnowledgeArticle, "article_code", "KB"),
        author=user.id,
        author_name=person.name if person else user.username,
    )
    db.add(article)
    db.flush()
    audit(db, "knowledge_article", article.id, "import", user,
          {"code": article.article_code, "filename": file.filename, "format": doc["content_format"]})
    db.commit()
    return ok({"article_id": article.id, "article_code": article.article_code, "title": article.title})


@router.post("/{article_id}/vote")
def vote(article_id: str, db: Session = Depends(get_db), user: AuthUser = Depends(get_current_user)):
    a = db.get(KnowledgeArticle, article_id)
    if not a or a.is_deleted or a.status != "published":
        raise AppError("NOT_FOUND", "文章不存在", 404)
    ensure_not_example(a)
    if a.author == user.id:
        raise AppError("SELF_VOTE", "不能给自己的文章点有用")
    dup = db.query(KnowledgeVote).filter_by(article_id=a.id, person=user.id).filter(KnowledgeVote.is_deleted.is_(False)).first()
    if dup:
        raise AppError("DUPLICATE", "已经点过了")
    db.add(KnowledgeVote(article_id=a.id, person=user.id))
    a.helpful_count = (a.helpful_count or 0) + 1
    publish(db, "knowledge.voted", "knowledge_article", a.id, {"voter": user.id})
    db.commit()
    return ok({"id": a.id, "helpful_count": a.helpful_count})
