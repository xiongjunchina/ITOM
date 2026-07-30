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


settings = Settings()
