"""飞书机器人发送的服务请求闭环交互卡片。

普通对话仍由 Aily 通过 MCP 访问 ITOM；卡片按钮是唯一例外，按钮仅携带公开工单号、
动作和幂等键，由 ITOM 的飞书回调入口验签、映射点击人并调用同一领域服务。
"""


def _callback_action(
    *,
    action: str,
    ticket_code: str,
    idempotency_key: str,
    score: int | None = None,
) -> dict:
    value = {
        "itom_action": action,
        "ticket_code": ticket_code,
        "idempotency_key": idempotency_key,
    }
    if score is not None:
        value["score"] = score
    return value


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
                        "value": _callback_action(
                            action="confirm_resolved",
                            ticket_code=ticket_code,
                            idempotency_key=f"card:{ticket_code}:confirm:{cycle}",
                        ),
                    },
                    {
                        "tag": "button",
                        "type": "default",
                        "text": {"tag": "plain_text", "content": "仍未解决"},
                        "value": _callback_action(
                            action="show_reopen_form",
                            ticket_code=ticket_code,
                            idempotency_key=f"card:{ticket_code}:reopen:{cycle}",
                        ),
                    },
                ],
            },
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": "按钮回调由 ITOM 验证飞书签名和点击人身份，并执行本人范围、状态与幂等校验。",
                    }
                ],
            },
        ],
    )


def build_rating_card(
    *,
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
                "value": _callback_action(
                    action="rate",
                    ticket_code=ticket_code,
                    score=score,
                    idempotency_key=f"card:{ticket_code}:rate:{score}",
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


def build_reopen_feedback_card(
    *,
    ticket_code: str,
    title: str,
    solution: str,
    idempotency_key: str,
) -> dict:
    """把解决确认卡片原地切换为“未解决原因”必填表单。"""
    return _base_card(
        title="请说明仍未解决的情况",
        template="orange",
        elements=[
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**工单编号：** {ticket_code}\n"
                        f"**标题：** {title}\n"
                        f"**本次解决说明：** {solution or '详见服务请求处理记录'}"
                    ),
                },
            },
            {
                "tag": "form",
                "name": "itom_reopen_form",
                "elements": [
                    {
                        "tag": "input",
                        "name": "feedback",
                        "required": True,
                        "input_type": "multiline_text",
                        "rows": 3,
                        "max_length": 500,
                        "placeholder": {
                            "tag": "plain_text",
                            "content": "请描述仍存在的现象，至少 2 个字符",
                        },
                        "label": {
                            "tag": "plain_text",
                            "content": "未解决原因",
                        },
                    },
                    {
                        "tag": "button",
                        "type": "primary",
                        "action_type": "form_submit",
                        "name": "submit_reopen",
                        "text": {"tag": "plain_text", "content": "提交并重新打开"},
                        "value": _callback_action(
                            action="reopen",
                            ticket_code=ticket_code,
                            idempotency_key=idempotency_key,
                        ),
                    },
                ],
            },
        ],
    )


def build_action_result_card(
    *,
    title: str,
    content: str,
    template: str = "green",
) -> dict:
    """生成不可重复操作的回调结果卡片。"""
    return _base_card(
        title=title,
        template=template,
        elements=[
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": content},
            }
        ],
    )
