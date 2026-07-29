"""清理冻结版飞书服务台表和字段。

默认只打印计划；仅在 PostgreSQL 且传入 ``--confirm`` 时执行。
"""
import argparse


STATEMENTS = (
    "DROP TABLE IF EXISTS feishu_helpdesk_outbox CASCADE",
    "DROP TABLE IF EXISTS feishu_helpdesk_sync_event CASCADE",
    "DROP TABLE IF EXISTS feishu_helpdesk_handoff CASCADE",
    "DROP TABLE IF EXISTS feishu_helpdesk_intake CASCADE",
    "ALTER TABLE feishu_config DROP COLUMN IF EXISTS helpdesk_id",
    "ALTER TABLE feishu_config DROP COLUMN IF EXISTS helpdesk_token_encrypted",
    "ALTER TABLE feishu_config DROP COLUMN IF EXISTS helpdesk_enabled",
    "ALTER TABLE feishu_config DROP COLUMN IF EXISTS helpdesk_event_verification_token_encrypted",
    "ALTER TABLE feishu_config DROP COLUMN IF EXISTS helpdesk_event_url",
    "ALTER TABLE feishu_config DROP COLUMN IF EXISTS helpdesk_event_subscription_status",
    "ALTER TABLE feishu_config DROP COLUMN IF EXISTS helpdesk_event_subscription_at",
    "ALTER TABLE feishu_config DROP COLUMN IF EXISTS helpdesk_event_subscription_error",
)


def render_plan() -> str:
    return "\n".join(f"{index}. {statement};" for index, statement in enumerate(STATEMENTS, 1))


def apply_cleanup() -> None:
    from sqlalchemy import text

    from app.db import SessionLocal

    with SessionLocal() as db:
        if db.get_bind().dialect.name != "postgresql":
            raise RuntimeError("Aily MCP 清理脚本只允许在 PostgreSQL 执行")
        for statement in STATEMENTS:
            db.execute(text(statement))
        db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="预览或执行飞书服务台数据结构清理")
    parser.add_argument("--confirm", action="store_true", help="确认永久删除服务台表、历史数据及专用配置列")
    args = parser.parse_args()
    print("飞书服务台清理计划：")
    print(render_plan())
    if not args.confirm:
        print("仅预览，未执行。确认后请追加 --confirm。")
        return
    apply_cleanup()
    print("清理完成。")


if __name__ == "__main__":
    main()
