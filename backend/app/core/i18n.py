"""后端 i18n（M7.2）：按请求语言本地化 status_name 与错误消息。

- 语言来自请求头 `X-Lang`（zh/en，默认 zh），中间件写入 contextvar。
- status_name：内置状态码 → en 映射（自定义状态无 en 时回退中文库名）。
- 错误消息：按中文原文查 en 映射（保留上下文；动态 f-string 消息回退中文）。
- 数据字典值、部门/人名、用户录入内容属"内容"非"UI"，不在此翻译。
"""
from contextvars import ContextVar

_lang: ContextVar[str] = ContextVar("lang", default="zh")


def set_lang(lang: str) -> None:
    _lang.set("en" if lang == "en" else "zh")


def get_lang() -> str:
    return _lang.get()


# ---------- 状态码 → 英文（与前端 enums.ts 保持一致） ----------
STATUS_EN: dict[str, dict[str, str]] = {
    "ticket": {"new": "New", "processing": "Processing", "paused": "On hold",
               "resolved": "Resolved", "closed": "Closed"},
    "ticket_change": {"new": "New", "pending_approval": "Pending approval", "approved": "Approved",
                      "rejected": "Rejected", "implementing": "Implementing", "rolled_back": "Rolled back",
                      "resolved": "Resolved", "closed": "Closed"},
    "problem": {"new": "New", "analyzing": "Analyzing", "known_error": "Known Error",
                "resolved": "Resolved", "closed": "Closed"},
    "project": {"planning": "Planning", "active": "In progress", "paused": "Paused",
                "completed": "Completed", "closed": "Closed", "cancelled": "Cancelled"},
    "requirement": {"registered": "Registered", "analyzing": "Analyzing", "implementing": "Implementing",
                    "closed": "Closed", "on_hold": "On hold", "cancelled": "Cancelled"},
    "idea": {"submitted": "Submitted", "adopted": "Adopted", "implemented": "Implemented", "declined": "Declined"},
    "campaign": {"draft": "Draft", "active": "Active", "offline": "Offline"},
}


def localize_status(entity_type: str, code: str, zh_name: str) -> str:
    if get_lang() == "en":
        return STATUS_EN.get(entity_type, {}).get(code, zh_name)
    return zh_name


def localize_status_map(entity_type: str, zh_map: dict[str, str]) -> dict[str, str]:
    if get_lang() != "en":
        return zh_map
    en = STATUS_EN.get(entity_type, {})
    return {code: en.get(code, name) for code, name in zh_map.items()}


# ---------- 错误消息（中文原文 → 英文；保留上下文） ----------
MESSAGE_EN: dict[str, str] = {
    "admin 不允许作为开通默认角色，请在用户管理单独分配": "The admin role can't be a provisioning default; assign it separately in User Management",
    "admin 不允许通过用户组授予，请在用户管理单独分配": "The admin role can't be granted via user groups; assign it separately in User Management",
    "admin 隐式全权，不可配置": "admin has implicit full access and is not configurable",
    "dept_type 取值必须为 it/business/audit": "dept_type must be it/business/audit",
    "match_type 必须为 dept_type 或 department": "match_type must be dept_type or department",
    "上级部门不能是自己": "A department can't be its own parent",
    "不允许继承 admin，请直接为用户分配 admin 角色": "Inheriting admin is not allowed; assign the admin role to the user directly",
    "不允许自环流转": "Self-loop transitions are not allowed",
    "不能与自身建立关系": "Can't create a relationship with itself",
    "不能给自己的建言点赞": "You can't like your own suggestion",
    "不能给自己的文章点有用": "You can't mark your own article as helpful",
    "业务域不存在": "Business domain not found",
    "业务域编码已存在": "Business domain code already exists",
    "人员不存在": "Person not found",
    "仅任务负责人可更新自己任务的状态；其他修改需需求编辑权限": "Only the task owner can update their task status; other changes require requirement edit permission",
    "仅任务负责人可更新自己任务的状态；其他修改需项目编辑权限": "Only the task owner can update their task status; other changes require project edit permission",
    "仅作者或负责人可编辑": "Only the author or owner can edit",
    "任务不存在": "Task not found",
    "优先级必须为 M/S/C/W": "Priority must be M/S/C/W",
    "供应商不存在": "Vendor not found",
    "关系不存在": "Relationship not found",
    "关系已存在": "Relationship already exists",
    "关联人员不存在": "Linked person not found",
    "关联服务项不存在": "Linked service item not found",
    "关联项目不存在": "Linked project not found",
    "内置角色不可删除": "Built-in roles can't be deleted",
    "内置角色的代码与继承关系不可修改（名称/描述可以）": "A built-in role's code and inheritance can't be changed (name/description can)",
    "凭证已过期，请重新登录": "Your session has expired, please sign in again",
    "加减分事项不存在": "Adjustment entry not found",
    "包含不存在的人员": "Contains a non-existent person",
    "包含不存在的用户组": "Contains a non-existent user group",
    "变更工单必须选择变更类型": "A change ticket must have a change type",
    "只有提交人可以评价": "Only the submitter can rate",
    "合同不存在": "Contract not found",
    "同一维度只能配置一次": "A dimension can only be configured once",
    "同步部门不可本地删除（外部源移除后自动停用）": "Synced departments can't be deleted locally (they deactivate when removed from the source)",
    "字典项不存在": "Dictionary item not found",
    "导入文件不能超过 5MB": "Import file must not exceed 5MB",
    "岗位不存在": "Position not found",
    "工单不存在": "Ticket not found",
    "工单关闭后才能评价": "You can rate only after the ticket is closed",
    "工单类型无效": "Invalid ticket type",
    "已经点过了": "Already voted",
    "已经点过赞了": "Already liked",
    "建言不存在": "Suggestion not found",
    "开通时不可直接授予 admin 角色": "The admin role can't be granted during provisioning",
    "当前角色无权执行此流转": "Your role can't perform this transition",
    "必须且只能有一个初始状态": "There must be exactly one initial status",
    "成本记录不存在": "Cost entry not found",
    "所属业务域不存在或已停用": "The business domain doesn't exist or is inactive",
    "招聘需求不存在": "Hiring need not found",
    "文章不存在": "Article not found",
    "无权查看他人工单": "You can't view others' tickets",
    "无权查看他人需求": "You can't view others' requirements",
    "无法删除：仍有人员归属该部门": "Can't delete: people still belong to this department",
    "无法删除：存在下级部门": "Can't delete: sub-departments exist",
    "无法删除：流程步骤引用了该用户组": "Can't delete: a process step references this user group",
    "无法删除：状态机流转规则引用了该用户组": "Can't delete: a state-machine transition references this user group",
    "服务项不存在": "Service item not found",
    "服务项不存在或已下架": "The service item doesn't exist or is unlisted",
    "未登录或凭证无效": "Not signed in or invalid credentials",
    "未知的评分维度": "Unknown scoring dimension",
    "步骤序号必须从 1 连续递增": "Step numbers must increment continuously from 1",
    "没有执行此操作的权限": "You don't have permission for this action",
    "没有该功能的操作权限，请联系管理员配置": "You don't have permission for this feature; contact an administrator",
    "活动不存在": "Campaign not found",
    "活动未上架": "The campaign is not active",
    "活动未上架，不能发放积分": "The campaign is not active; points can't be awarded",
    "流程代码已存在": "Process code already exists",
    "流程任务不存在": "Process task not found",
    "流程定义不存在": "Process definition not found",
    "激励任务不存在": "Incentive task not found",
    "父任务不存在": "Parent task not found",
    "状态代码重复": "Duplicate status code",
    "状态必须为 待处理/进行中/已完成": "Status must be To do/In progress/Done",
    "状态必须为 未开始/进行中/已完成": "Status must be Not started/In progress/Done",
    "用户不存在": "User not found",
    "用户名已存在": "Username already exists",
    "用户名或密码错误": "Wrong username or password",
    "用户组不存在": "User group not found",
    "用户组代码已存在": "User group code already exists",
    "登录会话已失效，请重新扫码": "Login session expired, please scan again",
    "登录请求不存在": "Login request not found",
    "目录不存在": "Catalog not found",
    "示例数据仅供学习参考，不可修改或删除": "Example data is for reference only and can't be modified or deleted",
    "积分规则不存在": "Point rule not found",
    "章程文档不能超过 10MB": "The charter document must not exceed 10MB",
    "组合不存在": "Portfolio not found",
    "组合名称已存在": "Portfolio name already exists",
    "终态工单不可编辑": "A ticket in a terminal state can't be edited",
    "终态需求不可编辑": "A requirement in a terminal state can't be edited",
    "终态项目不可导入": "A project in a terminal state can't be imported into",
    "终态项目不可编辑": "A project in a terminal state can't be edited",
    "结束日期不能早于开始日期": "The end date can't be earlier than the start date",
    "结束日期必须晚于开始日期": "The end date must be later than the start date",
    "继承角色必须是内置角色": "The inherited role must be a built-in role",
    "考核期格式应为 YYYY-Q1/Q2/Q3 或 YYYY-All（全年考核）": "Assessment period must be YYYY-Q1/Q2/Q3 or YYYY-All (full-year)",
    "至少需要一个终态": "At least one terminal status is required",
    "草稿仅作者可见": "Drafts are visible only to the author",
    "角色不存在": "Role not found",
    "角色代码已存在": "Role code already exists",
    "计分方案不存在": "Scoring scheme not found",
    "计划结束不能早于计划开始": "Planned end can't be earlier than planned start",
    "评分须为 1-5": "The score must be 1-5",
    "该任务已处理": "This task has already been handled",
    "该工单已关联": "This ticket is already linked",
    "该工单已关联问题": "This ticket is already linked to a problem",
    "该类目下编码已存在": "The code already exists in this category",
    "该请求已处理": "This request has already been processed",
    "请上传 .docx 章程文档": "Please upload a .docx charter document",
    "请上传 .xlsx 文件（使用系统导出的模板）": "Please upload an .xlsx file (use the exported template)",
    "请先删除子任务": "Please delete sub-tasks first",
    "账号不可用，请联系管理员": "Account unavailable, please contact an administrator",
    "账号不存在或已禁用": "Account doesn't exist or is disabled",
    "账号已禁用": "Account is disabled",
    "账号已禁用，请联系管理员": "Account is disabled, please contact an administrator",
    "进入实现前需完成分析：优先级(MoSCoW)与负责人必填": "Finish analysis before implementation: priority (MoSCoW) and owner are required",
    "通知不存在": "Notification not found",
    "部门不存在": "Department not found",
    "部门类型必须为 it/business/audit": "Department type must be it/business/audit",
    "账号已禁用，请联系管理员": "Account is disabled, please contact an administrator",
}


def localize_message(zh_message: str) -> str:
    """错误消息本地化：en 且命中静态映射时译，否则回退中文（动态 f-string 消息保留中文）。"""
    if get_lang() == "en":
        return MESSAGE_EN.get(zh_message, zh_message)
    return zh_message
