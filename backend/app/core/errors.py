class AppError(Exception):
    """业务错误：统一转为 {success:false, error:{code,message}}。"""

    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)
