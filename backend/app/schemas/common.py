from typing import Any


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
