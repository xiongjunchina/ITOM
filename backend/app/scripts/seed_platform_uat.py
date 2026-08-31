"""CLI：显式创建或清理仅本地使用的平台运营 P0 合成数据。"""

from __future__ import annotations

import argparse
import json

from app.core.config import settings
from app.db import SessionLocal
from app.services.seed_platform_uat import cleanup_platform_uat, seed_platform_uat
from app.services.seed_table_uat import assert_local_uat_database


def main() -> int:
    parser = argparse.ArgumentParser(description="管理仅本地使用的平台运营 UAT 合成数据")
    parser.add_argument("action", choices=("seed", "cleanup"))
    parser.add_argument("--confirm-local", action="store_true", help="确认目标是本地 SQLite/Docker Compose 数据库")
    args = parser.parse_args()
    if not args.confirm_local:
        parser.error("必须显式传入 --confirm-local")
    assert_local_uat_database(settings.database_url)
    with SessionLocal() as db:
        result = seed_platform_uat(db) if args.action == "seed" else cleanup_platform_uat(db)
        db.commit()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
