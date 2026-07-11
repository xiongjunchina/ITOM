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
        raise AppError("EXAMPLE_READONLY", "示例数据仅供学习参考，不可修改或删除", 403)
