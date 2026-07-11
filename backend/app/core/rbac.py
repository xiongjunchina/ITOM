"""角色定义（PRD §2.1）。admin 隐式拥有全部权限。"""

ADMIN = "admin"
CIO = "cio"            # IT 总负责人
IT_BM = "it_bm"        # IT 业务线负责人（横向服务线，业务域 owner 通常持此角色）
IT_TM = "it_tm"        # IT 专业线负责人（纵向资源池，用户组 owner 通常持此角色）
IT_PDM = "it_pdm"      # IT 产品经理
IT_PM = "it_pm"        # IT 项目经理
IT_DEV = "it_dev"
IT_OPS = "it_ops"
IS_MGR = "is_mgr"      # 信息安全管理员
IT_BP = "it_bp"        # IT 业务合作伙伴
AUDITOR = "auditor"    # 审计员：全模块只读 + 审计日志
REQUESTER = "requester"

ALL_ROLES = [ADMIN, CIO, IT_BM, IT_TM, IT_PDM, IT_PM, IT_DEV, IT_OPS, IS_MGR, IT_BP, AUDITOR, REQUESTER]
TEAM_ROLES = [CIO, IT_BM, IT_TM, IT_PDM, IT_PM, IT_DEV, IT_OPS, IS_MGR, IT_BP]  # 内部团队成员（可被派单）
