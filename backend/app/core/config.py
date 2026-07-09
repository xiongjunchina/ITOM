from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str = "postgresql+psycopg2://aom:aom@localhost:6432/new_aom"
    jwt_secret: str = "dev-secret-change-me"
    jwt_expire_hours: int = 8
    admin_init_password: str = "admin123"
    upload_dir: str = "uploads"


settings = Settings()
