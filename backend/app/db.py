from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, String, create_engine, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.core.config import settings
from app.core.glid import new_glid

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# JSON 列：PG 用 JSONB，测试用 sqlite 时退化为 JSON
JsonCol = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class GlidBase(Base):
    """所有业务表基类：GLID 主键 + 审计时间戳 + 软删除。"""

    __abstract__ = True

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_glid)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    is_example: Mapped[bool] = mapped_column(Boolean, default=False, comment="示例数据：置顶展示且只读")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
