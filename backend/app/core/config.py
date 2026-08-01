from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str = "postgresql+psycopg2://aom:aom@localhost:6432/new_aom"
    jwt_secret: str = "dev-secret-change-me"
    jwt_expire_hours: int = 8
    admin_init_password: str = "admin123"
    # 飞书业务用户自动开户的初始口令；部署环境可通过 BUSINESS_INITIAL_PASSWORD 覆盖。
    business_initial_password: str = "IT020@sn.local"
    upload_dir: str = "uploads"
    # OpenAI-compatible providers are denied unless their HTTPS host is listed here.
    ai_provider_allowed_hosts: str = ""
    ai_provider_connect_timeout_seconds: int = 5
    ai_provider_read_timeout_seconds: int = 60
    # A synchronous L1/L2 capability runs in a bounded read-only worker.  The
    # Python worker itself cannot be force-killed, so database work receives a
    # stricter transaction-local deadline and the caller stops waiting at the
    # tool deadline.
    ai_assistant_tool_timeout_seconds: float = 5.0
    ai_assistant_tool_statement_timeout_ms: int = 4000


settings = Settings()
