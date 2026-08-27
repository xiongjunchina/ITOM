"""CLI for explicitly creating or cleaning local wide-table UAT data."""

from __future__ import annotations

import argparse
import json

from app.core.config import settings
from app.db import SessionLocal
from app.services.seed_table_uat import (
    assert_local_uat_database,
    cleanup_table_uat,
    seed_table_uat,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="管理仅本地使用的表格 UAT 合成数据")
    parser.add_argument("action", choices=("seed", "cleanup"))
    parser.add_argument(
        "--confirm-local",
        action="store_true",
        help="确认目标是仓库定义的本地 SQLite/Docker Compose 数据库",
    )
    args = parser.parse_args()
    if not args.confirm_local:
        parser.error("必须显式传入 --confirm-local")
    assert_local_uat_database(settings.database_url)
    with SessionLocal() as db:
        result = seed_table_uat(db) if args.action == "seed" else cleanup_table_uat(db)
        # Session 上下文只负责关闭连接，不会自动提交；UAT 命令必须在本地
        # 目标复核通过后显式提交，否则终端虽然打印成功，页面数据仍会回滚。
        db.commit()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
