---
name: itom-service-request-closure
description: 处理 ITOM 服务请求解决确认、未解决重开和关闭后评价；适用于 Aily 卡片按钮或用户明确表达这些动作时。
---

# ITOM 服务请求闭环

只处理当前飞书用户本人的 ITOM 服务请求闭环动作。ITOM 是业务状态、权限、流程和审计的唯一依据；不得直接访问数据库或调用未批准的接口。

## 可用动作

1. `confirm_resolved`：用户明确确认问题已解决并关闭。
2. `reopen`：用户确认仍未解决，需要重新处理。
3. `rate`：用户为已关闭服务请求提交 1–5 星评价，可选标签和意见。

动作可能来自交互卡片的 `skill_input`，也可能来自自然语言消息。始终以公开工单编号 `ticket_code` 定位单据；不得猜测“最近一张”。

## 执行流程

### 已解决并关闭

- 必须具有明确 `ticket_code`。
- 卡片点击或用户明确说“已解决并关闭”即为本次动作确认，不重复追问。
- 调用 ITOM MCP `confirm_service_request_resolution`：`resolved=true`。
- 优先使用卡片提供的 `idempotency_key`；没有时生成新的 8–128 字符唯一键。
- 返回工单编号和关闭结果，不展示内部 ID、JWT 或飞书身份标识。

### 仍未解决

- 必须具有明确 `ticket_code`。
- 如果尚无具体反馈，只追问一次“仍未解决的现象是什么”，不得先调用写工具。
- 获得反馈后调用 ITOM MCP `confirm_service_request_resolution`：`resolved=false`，`feedback` 使用用户原意的简洁描述。
- 优先使用卡片提供的 `idempotency_key`；没有时生成新的 8–128 字符唯一键。
- 返回重开结果和当前公开状态，不承诺尚未发生的派单或解决时间。

### 星级评价

- 必须具有明确 `ticket_code` 和 1–5 的 `score`。
- 点击星级按钮即为提交该评分的明确确认，不再追问是否确认。
- 有标签或意见时一并传入；没有时直接提交评分，不强迫用户补充。
- 调用 ITOM MCP `rate_service_request`，优先使用卡片提供的 `idempotency_key`；没有时生成新的 8–128 字符唯一键。
- 返回已记录的星级；用户之后补充标签或意见时，可以使用新幂等键更新同一条有效评价。

## 安全与失败处理

- MCP 身份校验、本人范围、状态校验或权限校验失败时，如实返回错误，不尝试绕过。
- 不展示或复述 `open_id`、`user_id`、`tenant_id`、Agent ID、JWT、ITOM 内部主键、内部备注、根因或审批信息。
- 不把聊天记忆作为工单状态依据；需要状态时调用 ITOM MCP 实时查询。
- 同一次动作重试必须复用同一幂等键；参数发生变化时必须生成新键。

## English summary

Handle only the current Feishu user's own ITOM service-request closure actions. Card clicks are explicit confirmation for close or rating. A reopen must collect the unresolved symptom before calling MCP. All mutations use `confirm_service_request_resolution` or `rate_service_request`, preserve idempotency, and never bypass ITOM authorization, workflow, or audit.
