from typing import Any


def ok(data: Any = None, total: int | None = None, page: int | None = None) -> dict:
    body: dict = {"success": True, "data": data}
    if total is not None:
        body["total"] = total
    if page is not None:
        body["page"] = page
    return body


def paginate(query, page: int, page_size: int):
    """返回 (items, total)。page_size 上限 200。"""
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return items, total
