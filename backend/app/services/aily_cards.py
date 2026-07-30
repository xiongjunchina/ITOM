"""Aily 服务请求闭环交互卡片。

卡片按钮只负责触发 Aily 卡片动作技能；该技能必须继续调用 ITOM MCP
工具完成身份校验、本人范围检查、幂等和业务状态迁移，卡片本身不承载写权限。
"""

import json


def _skill_action(
    *,
    skill_id: str,
    message: str,
    skill_input: dict,
    update_card: bool,
    success_message: str,
) -> dict:
    return {
        "x_aily_forbid_forward_callback": True,
        "aily_action": "trigger_skill",
        "skill_id": skill_id,
        "message": message,
        "skill_input": json.dumps(
            skill_input,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "update_card": update_card,
        "success_message": success_message,
    }


def _base_card(*, title: str, template: str, elements: list[dict]) -> dict:
    return {
        "config": {
            "wide_screen_mode": True,
            "enable_forward": False,
        },
        "header": {
            "template": template,
            "title": {"tag": "plain_text", "content": title},
        },
        "elements": elements,
    }


def build_resolution_confirmation_card(
    *,
    skill_id: str,
    ticket_code: str,
    title: str,
    solution: str,
    confirmation_due_at: str | None,
    reopen_count: int,
) -> dict:
    """生成“已解决关闭 / 仍未解决”二选一卡片。"""
    cycle = max(0, reopen_count)
    due_line = (
        f"\n**请在 {confirmation_due_at} 前确认**"
        if confirmation_due_at
        else ""
    )
    common = {"ticket_code": ticket_code}
    return _base_card(
        title="服务请求待您确认",
        template="blue",
        elements=[
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**工单编号：** {ticket_code}\n"
                        f"**标题：** {title}\n"
                        f"**解决说明：** {solution}{due_line}"
                    ),
                },
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "type": "primary",
                        "text": {"tag": "plain_text", "content": "已解决并关闭"},
                        "value": _skill_action(
                            skill_id=skill_id,
                            message=f"确认 {ticket_code} 已解决并关闭",
                            skill_input={
                                **common,
                                "operation": "confirm_resolved",
                                "idempotency_key": f"card:{ticket_code}:confirm:{cycle}",
                            },
                            update_card=True,
                            success_message="已提交关闭确认",
                        ),
                    },
                    {
                        "tag": "button",
                        "type": "default",
                        "text": {"tag": "plain_text", "content": "仍未解决"},
                        "value": _skill_action(
                            skill_id=skill_id,
                            message=f"{ticket_code} 仍未解决，请记录我的反馈并重新处理",
                            skill_input={
                                **common,
                                "operation": "reopen",
                                "idempotency_key": f"card:{ticket_code}:reopen:{cycle}",
                            },
                            # Aily 技能还需要追问未解决原因，不能提前锁定卡片。
                            update_card=False,
                            success_message="请继续补充未解决原因",
                        ),
                    },
                ],
            },
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": "按钮将唤起 Aily，并由 Aily 通过 ITOM MCP 校验本人权限后执行。",
                    }
                ],
            },
        ],
    )


def build_rating_card(
    *,
    skill_id: str,
    ticket_code: str,
    title: str,
) -> dict:
    """生成 1–5 星即时评价卡片。"""
    actions = []
    for score in range(1, 6):
        actions.append(
            {
                "tag": "button",
                "type": "primary" if score == 5 else "default",
                "text": {"tag": "plain_text", "content": f"{score} 星"},
                "value": _skill_action(
                    skill_id=skill_id,
                    message=f"为 {ticket_code} 提交 {score} 星评价",
                    skill_input={
                        "ticket_code": ticket_code,
                        "operation": "rate",
                        "score": score,
                        "idempotency_key": f"card:{ticket_code}:rate:{score}",
                    },
                    update_card=True,
                    success_message=f"已提交 {score} 星评价，感谢反馈",
                ),
            }
        )
    return _base_card(
        title="请评价本次 IT 服务",
        template="green",
        elements=[
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**工单编号：** {ticket_code}\n**标题：** {title}\n点击星级即可评价。",
                },
            },
            {"tag": "action", "actions": actions},
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": "如需补充标签或意见，可继续在 Aily 对话中说明。",
                    }
                ],
            },
        ],
    )
