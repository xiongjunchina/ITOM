"""业务编号生成：前缀-YYYYMM-序号（docs/04 §0）。"""
from datetime import datetime

from sqlalchemy.orm import Session


def gen_code(db: Session, model, code_field: str, prefix: str) -> str:
    """按月递增序号。单团队并发规模下用 max+1，唯一索引兜底。"""
    ym = datetime.now().strftime("%Y%m")
    head = f"{prefix}-{ym}-"
    col = getattr(model, code_field)
    last = (
        db.query(col)
        .filter(col.like(f"{head}%"))
        .order_by(col.desc())
        .first()
    )
    seq = int(last[0].rsplit("-", 1)[1]) + 1 if last else 1
    return f"{head}{seq:04d}"
