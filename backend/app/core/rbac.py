"""角色定义（PRD §2.1）。admin 隐式拥有全部权限。"""

ADMIN = "admin"
MANAGER = "manager"
IT_PDM = "it_pdm"      # IT 产品经理
IT_PM = "it_pm"        # IT 项目经理
IT_DEV = "it_dev"
IT_OPS = "it_ops"
IS_MGR = "is_mgr"      # 信息安全管理员
IT_BP = "it_bp"        # IT 业务合作伙伴
REQUESTER = "requester"

ALL_ROLES = [ADMIN, MANAGER, IT_PDM, IT_PM, IT_DEV, IT_OPS, IS_MGR, IT_BP, REQUESTER]
TEAM_ROLES = [MANAGER, IT_PDM, IT_PM, IT_DEV, IT_OPS, IS_MGR, IT_BP]  # 内部团队成员
