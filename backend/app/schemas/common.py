from typing import Any

from pydantic import BaseModel, Field


class BatchDeleteIn(BaseModel):
    """批量删除请求。

    路由仍须逐条调用自身实体的删除规则；这个模型只约束一次请求的
    输入规模，不能作为绕过状态、关联或权限校验的通用删除入口。
    """

    ids: list[str] = Field(min_length=1, max_length=100)


def ok(data: Any = None, total: int | None = None, page: int | None = None) -> dict:
    body: dict = {"success": True, "data": data}
    if total is not None:
        body["total"] = total
    if page is not None:
        body["page"] = page
    return body


def paginate(query, page: int, page_size: int, max_size: int = 200):
    """返回 (items, total)。page_size 上限默认 200；下拉全量场景（如人员）可放宽。"""
    page = max(page, 1)
    page_size = min(max(page_size, 1), max_size)
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return items, total
