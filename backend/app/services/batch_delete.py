"""批量删除的事务编排。

每个业务路由传入自己的 ``delete_one``：权限、流程状态、引用关系和
审计规则仍由该实体的单条删除逻辑执行。本模块只提供逐项 savepoint、
部分成功结果和一次最终提交，避免任何“万能删除”绕过领域约束。
"""

from collections.abc import Callable

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError


def execute_batch_delete(
    db: Session,
    ids: list[str],
    delete_one: Callable[[str], None],
) -> dict:
    deleted_ids: list[str] = []
    rejected: list[dict[str, str]] = []

    # 保持前端选择顺序，并忽略重复选择，避免重复请求将同一条记录误报为失败。
    for entity_id in dict.fromkeys(ids):
        try:
            with db.begin_nested():
                delete_one(entity_id)
                db.flush()
            deleted_ids.append(entity_id)
        except AppError as exc:
            rejected.append({"id": entity_id, "code": exc.code, "message": exc.message})
        except SQLAlchemyError:
            rejected.append({"id": entity_id, "code": "DELETE_FAILED", "message": "删除失败，请稍后重试"})

    if deleted_ids:
        db.commit()

    return {"deleted_ids": deleted_ids, "rejected": rejected}
