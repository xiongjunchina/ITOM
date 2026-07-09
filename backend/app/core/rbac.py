"""角色定义（PRD §2.1）。admin 隐式拥有全部权限。"""

ADMIN = "admin"
MANAGER = "manager"
IT_PM = "it_pm"        # IT 产品经理
IT_PJM = "it_pjm"      # IT 项目经理
IT_DEV = "it_dev"
IT_OPS = "it_ops"
IS_MGR = "is_mgr"      # 信息安全管理员
REQUESTER = "requester"

ALL_ROLES = [ADMIN, MANAGER, IT_PM, IT_PJM, IT_DEV, IT_OPS, IS_MGR, REQUESTER]
TEAM_ROLES = [MANAGER, IT_PM, IT_PJM, IT_DEV, IT_OPS, IS_MGR]  # 内部团队成员
