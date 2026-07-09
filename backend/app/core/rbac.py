"""角色定义（PRD §2.1）。admin 隐式拥有全部权限。"""

ADMIN = "admin"
MANAGER = "manager"
IT_PM = "it_pm"
IT_DEV = "it_dev"
IT_OPS = "it_ops"
REQUESTER = "requester"

ALL_ROLES = [ADMIN, MANAGER, IT_PM, IT_DEV, IT_OPS, REQUESTER]
TEAM_ROLES = [MANAGER, IT_PM, IT_DEV, IT_OPS]  # 内部团队成员
