/**
 * 共享枚举/状态标签的双语显示（M7 增量双语）。
 *
 * 约定：中文枚举「值」是后端存储的规范数据（如工单状态"待处理"、招聘状态"待招聘"、
 * 需求类型"功能"），**不翻译数据本身**；这里只提供「显示」层的英文渲染——
 * zh 返回原值/原中文标签，en 返回英文标签，回退原值。颜色映射仍在 types.ts（与语言无关）。
 *
 * 用法：`const et = useEnums(); et.hiringStatus(row.status)` / `et.role(code)`。
 * 下拉项：`HIRING_STATUSES.map(v => ({ value: v, label: et.hiringStatus(v) }))`（value 保持中文）。
 */
import { useLangStore } from './store';

type M = Record<string, string>;

// code 键（后端用英文码）：zh/en 均为标签
const ROLE_ZH: M = { admin: '系统管理员', cio: 'CIO(IT总负责人)', it_bm: 'IT业务线负责人', it_tm: 'IT专业线负责人', it_pdm: 'IT产品经理', it_pm: 'IT项目经理', it_pmo: 'IT PMO(项目管理办公室)', it_dev: 'IT开发', it_ops: 'IT运维', is_mgr: '信息安全管理员', it_bp: 'IT业务合作伙伴', auditor: '审计员', requester: '业务用户' };
const ROLE_EN: M = { admin: 'Administrator', cio: 'CIO (Head of IT)', it_bm: 'IT Business-line Lead', it_tm: 'IT Discipline-line Lead', it_pdm: 'IT Product Manager', it_pm: 'IT Project Manager', it_pmo: 'IT PMO (Project Management Office)', it_dev: 'IT Developer', it_ops: 'IT Operations', is_mgr: 'Information Security Manager', it_bp: 'IT Business Partner', auditor: 'Auditor', requester: 'Requester' };
const TICKET_TYPE_ZH: M = { incident: '事件', service_request: '服务请求', change: '变更' };
const TICKET_TYPE_EN: M = { incident: 'Incident', service_request: 'Service Request', change: 'Change' };
const PERM_ACTION_ZH: M = { view: '可见', create: '新建', edit: '修改', delete: '删除' };
const PERM_ACTION_EN: M = { view: 'View', create: 'Create', edit: 'Edit', delete: 'Delete' };
const DEPT_TYPE_ZH: M = { it: 'IT', business: '业务', audit: '审计' };
const DEPT_TYPE_EN: M = { it: 'IT', business: 'Business', audit: 'Audit' };
const PROVISION_MATCH_ZH: M = { dept_type: '按部门类型', department: '按具体部门' };
const PROVISION_MATCH_EN: M = { dept_type: 'By department type', department: 'By specific department' };
const WORKFLOW_ENTITY_ZH: M = { ticket: '工单（事件/服务请求）', ticket_change: '工单（变更）', requirement: '需求', project: '项目', problem: '问题' };
const WORKFLOW_ENTITY_EN: M = { ticket: 'Ticket (Incident/Service Request)', ticket_change: 'Ticket (Change)', requirement: 'Requirement', project: 'Project', problem: 'Problem' };
const AUTONOMY_ZH: M = { L1: 'L1 全自动', L2: 'L2 自动执行·人工确认', L3: 'L3 人工为主·系统辅助', L4: 'L4 纯人工' };
const AUTONOMY_EN: M = { L1: 'L1 Fully automated', L2: 'L2 Auto + human confirm', L3: 'L3 Human-led + system assist', L4: 'L4 Manual' };
const TIER_ZH: M = { gold: '金牌', silver: '银牌', bronze: '铜牌' };
const TIER_EN: M = { gold: 'Gold', silver: 'Silver', bronze: 'Bronze' };
const PROBLEM_STATUS_ZH: M = { new: '新建', analyzing: '分析中', known_error: '已知错误', resolved: '已解决', closed: '已关闭' };
const PROBLEM_STATUS_EN: M = { new: 'New', analyzing: 'Analyzing', known_error: 'Known Error', resolved: 'Resolved', closed: 'Closed' };
const HEALTH_ZH: M = { green: '正常', yellow: '预警', red: '风险' };
const HEALTH_EN: M = { green: 'Healthy', yellow: 'At risk', red: 'Critical' };
const MOSCOW_ZH: M = { M: 'M 必须', S: 'S 应该', C: 'C 可以', W: 'W 暂缓' };
const MOSCOW_EN: M = { M: 'M Must', S: 'S Should', C: 'C Could', W: "W Won't" };
const POINT_SOURCE_ZH: M = { ticket_resolved: '工单解决', ticket_sla_met: 'SLA达成', ticket_satisfaction: '满意度好评', idea_submit: '建言', idea_like: '被点赞', idea_adopt: '建言采纳', wbs_done_on_time: '任务按期', milestone_achieved: '里程碑', requirement_task_done: '需求任务', requirement_closed: '需求交付', knowledge_published: '发布知识', knowledge_voted: '知识好评', training_host: '主讲培训', training_attend: '参与培训', campaign_award: '专项活动' };
const POINT_SOURCE_EN: M = { ticket_resolved: 'Ticket resolved', ticket_sla_met: 'SLA met', ticket_satisfaction: 'Satisfaction', idea_submit: 'Suggestion', idea_like: 'Liked', idea_adopt: 'Suggestion adopted', wbs_done_on_time: 'Task on time', milestone_achieved: 'Milestone', requirement_task_done: 'Req task', requirement_closed: 'Req delivered', knowledge_published: 'Published KB', knowledge_voted: 'KB helpful', training_host: 'Training host', training_attend: 'Training attend', campaign_award: 'Campaign' };
const PROC_INST_ZH: M = { running: '进行中', completed: '已完成', cancelled: '已取消' };
const PROC_INST_EN: M = { running: 'Running', completed: 'Completed', cancelled: 'Cancelled' };
const PROC_ENTITY_ZH: M = { ticket: '工单', ticket_change: '变更', problem: '问题', project: '项目', requirement: '需求' };
const PROC_ENTITY_EN: M = { ticket: 'Ticket', ticket_change: 'Change', problem: 'Problem', project: 'Project', requirement: 'Requirement' };
const IDEA_STATUS_ZH: M = { submitted: '已提交', adopted: '已采纳', implemented: '已实现', declined: '已婉拒' };
const IDEA_STATUS_EN: M = { submitted: 'Submitted', adopted: 'Adopted', implemented: 'Implemented', declined: 'Declined' };
const CAMPAIGN_STATUS_ZH: M = { draft: '草稿', active: '上架中', offline: '已下架' };
const CAMPAIGN_STATUS_EN: M = { draft: 'Draft', active: 'Active', offline: 'Offline' };

// value 键（中文规范值）：zh 返回原值，en 查表回退原值
const CI_STATUS_EN: M = { 运行中: 'Running', 维护中: 'Maintenance', 已下线: 'Retired' };
const CI_ENV_EN: M = { 生产: 'Production', 测试: 'Test', 开发: 'Development' };
const CI_RELATION_EN: M = { 运行于: 'Runs on', 依赖: 'Depends on', 连接: 'Connects to' };
const VENDOR_STATUS_EN: M = { 合作中: 'Active', 已终止: 'Terminated' };
const CONTRACT_STATUS_EN: M = { 未生效: 'Not started', 生效: 'Active', 临期: 'Expiring', 已过期: 'Expired' };
const WBS_STATUS_EN: M = { 未开始: 'Not started', 进行中: 'In progress', 已完成: 'Done', 已延期: 'Overdue' };
const RISK_GRADE_EN: M = { 高: 'High', 中: 'Medium', 低: 'Low' };
const RISK_STATUS_EN: M = { 开放: 'Open', 已关闭: 'Closed' };
const REQ_TYPE_EN: M = { 业务: 'Business', 功能: 'Feature', 数据: 'Data', 集成: 'Integration', 合规: 'Compliance' };
const REQ_TASK_STATUS_EN: M = { 待处理: 'To do', 进行中: 'In progress', 已完成: 'Done' };
const HIRING_STATUS_EN: M = { 待招聘: 'To hire', 面试中: 'Interviewing', 已到岗: 'Onboarded', 已取消: 'Cancelled' };
const HIRING_LEVEL_EN: M = { 高级: 'Senior', 中级: 'Mid', 初级: 'Junior' };
const CATALOG_STATUS_EN: M = { 上架: 'Listed', 下架: 'Unlisted' };
const TRAINING_TYPE_EN: M = { 内部交叉培训: 'Internal cross-training', 外部技术交流: 'External tech exchange', 新技术研究: 'New-tech research' };
const CHANGE_TYPE_EN: M = { 标准: 'Standard', 普通: 'Normal', 紧急: 'Emergency' };
const GENDER_EN: M = { 男: 'Male', 女: 'Female' };
const EMPLOYMENT_EN: M = { 正式: 'Full-time', 外包: 'Outsourced', 实习: 'Intern' };
const MEMBER_STATUS_EN: M = { 在岗: 'Active', 离职: 'Left' };
// 项目/需求状态（按 code，与后端 STATUS_EN 一致；用于筛选下拉，列表徽标已由后端 status_name 本地化）
const PROJECT_STATUS_ZH: M = { planning: '规划中', active: '进行中', paused: '已暂停', completed: '已完成', closed: '已关闭', cancelled: '已取消' };
const PROJECT_STATUS_EN: M = { planning: 'Planning', active: 'In progress', paused: 'Paused', completed: 'Completed', closed: 'Closed', cancelled: 'Cancelled' };
const REQUIREMENT_STATUS_ZH: M = { registered: '已登记', evaluating: '评估中', analyzing: '分析中', implementing: '实现中', closed: '已关闭', on_hold: '已搁置', cancelled: '已取消' };
const REQUIREMENT_STATUS_EN: M = { registered: 'Registered', evaluating: 'Evaluating', analyzing: 'Analyzing', implementing: 'Implementing', closed: 'Closed', on_hold: 'On hold', cancelled: 'Cancelled' };
// 四象限 / 评估决议（value 键：中文规范值，en 查表回退原值）
const QUADRANT_EN: M = { 战略下注: 'Strategic Bet', 速赢项目: 'Quick Win', 低优先级: 'Low Priority', 重新评估: 'Re-evaluate' };
const REQ_DECISION_EN: M = { 立项: 'Approved', 搁置: 'On hold', 驳回: 'Rejected' };

/** 组件内使用：随语言 store 响应式返回双语枚举标签函数。 */
export function useEnums() {
  const lang = useLangStore((s) => s.lang);
  const code = (zh: M, en: M) => (c?: string | null) => (!c ? '' : lang === 'en' ? en[c] ?? zh[c] ?? c : zh[c] ?? c);
  const val = (en: M) => (v?: string | null) => (!v ? '' : lang === 'en' ? en[v] ?? v : v);
  return {
    role: code(ROLE_ZH, ROLE_EN),
    ticketType: code(TICKET_TYPE_ZH, TICKET_TYPE_EN),
    permAction: code(PERM_ACTION_ZH, PERM_ACTION_EN),
    deptType: code(DEPT_TYPE_ZH, DEPT_TYPE_EN),
    provisionMatch: code(PROVISION_MATCH_ZH, PROVISION_MATCH_EN),
    workflowEntity: code(WORKFLOW_ENTITY_ZH, WORKFLOW_ENTITY_EN),
    autonomy: code(AUTONOMY_ZH, AUTONOMY_EN),
    tier: code(TIER_ZH, TIER_EN),
    problemStatus: code(PROBLEM_STATUS_ZH, PROBLEM_STATUS_EN),
    health: code(HEALTH_ZH, HEALTH_EN),
    moscow: code(MOSCOW_ZH, MOSCOW_EN),
    pointSource: code(POINT_SOURCE_ZH, POINT_SOURCE_EN),
    processInstanceStatus: code(PROC_INST_ZH, PROC_INST_EN),
    processEntity: code(PROC_ENTITY_ZH, PROC_ENTITY_EN),
    ideaStatus: code(IDEA_STATUS_ZH, IDEA_STATUS_EN),
    campaignStatus: code(CAMPAIGN_STATUS_ZH, CAMPAIGN_STATUS_EN),
    ciStatus: val(CI_STATUS_EN),
    ciEnv: val(CI_ENV_EN),
    ciRelation: val(CI_RELATION_EN),
    vendorStatus: val(VENDOR_STATUS_EN),
    contractStatus: val(CONTRACT_STATUS_EN),
    wbsStatus: val(WBS_STATUS_EN),
    riskGrade: val(RISK_GRADE_EN),
    riskStatus: val(RISK_STATUS_EN),
    reqType: val(REQ_TYPE_EN),
    reqTaskStatus: val(REQ_TASK_STATUS_EN),
    hiringStatus: val(HIRING_STATUS_EN),
    hiringLevel: val(HIRING_LEVEL_EN),
    catalogStatus: val(CATALOG_STATUS_EN),
    trainingType: val(TRAINING_TYPE_EN),
    changeType: val(CHANGE_TYPE_EN),
    gender: val(GENDER_EN),
    employment: val(EMPLOYMENT_EN),
    memberStatus: val(MEMBER_STATUS_EN),
    projectStatus: code(PROJECT_STATUS_ZH, PROJECT_STATUS_EN),
    requirementStatus: code(REQUIREMENT_STATUS_ZH, REQUIREMENT_STATUS_EN),
    quadrant: val(QUADRANT_EN),
    reqDecision: val(REQ_DECISION_EN),
  };
}

export type Enums = ReturnType<typeof useEnums>;
