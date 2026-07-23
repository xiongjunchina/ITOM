class AppError(Exception):
    """业务错误：统一转为 {success:false, error:{code,message}}。"""

    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def ensure_not_example(obj):
    """业务示例数据只读（供全模块学习参考）。"""
    if getattr(obj, "is_example", False):
        raise AppError("EXAMPLE_READONLY", "示例数据仅供学习参考，不可修改；删除仅限系统管理员从列表页操作", 403)


def ensure_example_delete_allowed(obj, db, actor):
    """示例记录仍然只读，但允许系统管理员在列表页明确删除。"""
    if not getattr(obj, "is_example", False):
        return
    from app.core.rbac import ADMIN
    from app.services.rbac import actor_keys

    if actor is None or ADMIN not in actor_keys(db, actor):
        raise AppError("EXAMPLE_READONLY", "示例数据仅供学习参考，仅系统管理员可删除", 403)
