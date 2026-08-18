import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Alert,
  Anchor,
  Breadcrumb,
  Button,
  Card,
  Col,
  Empty,
  Input,
  List,
  Row,
  Space,
  Tag,
  Typography,
} from 'antd';
import {
  ApartmentOutlined,
  AppstoreOutlined,
  ArrowLeftOutlined,
  BookOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CustomerServiceOutlined,
  FireOutlined,
  InfoCircleOutlined,
  ProjectOutlined,
  RightOutlined,
  RocketOutlined,
  SearchOutlined,
  SettingOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import { useLangStore } from '../i18n/store';

const { Title, Text, Paragraph } = Typography;

type ManualSection = {
  id: string;
  title: string;
  summary: string;
  logic: string[];
  steps: string[];
  role?: string;
};

type HelpCategoryId = 'getting-started' | 'itsm' | 'projects' | 'requirements' | 'team' | 'process' | 'admin' | 'profile';

type HelpArticle = ManualSection & {
  category: HelpCategoryId;
  tags: string[];
  updated: string;
  featured?: boolean;
};

const ZH_SECTIONS: ManualSection[] = [
  {
    id: 'overview',
    title: '系统总体介绍',
    summary: 'ITOM 将 IT 服务、项目、需求、团队能力和流程治理集中到一个平台。',
    logic: [
      '采用“业务域 × 专业线”的矩阵式组织：业务域负责横向服务，用户组负责纵向资源池。',
      '所有人员选择默认来自管理员配置的数字化团队范围；范围是所选部门成员与单独指定人员的并集，组织架构由飞书或其他集成源同步。',
      '服务请求、事件、变更、问题、需求和项目通过流程节点推进状态；审批节点与处理节点分开管理。',
      '总览将服务请求、变更、事件、问题拆成四个独立面板，分别展示未关闭/处理中数量和 P1–P4 处理级别，不再重复展示跨模块 ITSM 汇总。',
      '人效评分按考核周期计算，角色贡献、团队贡献、外部满意度和学习成长积分分别取数后汇总。',
    ],
    steps: ['登录系统，确认右上角账号和角色。', '从左侧导航进入有权限的模块。', '使用页面搜索、筛选、排序和分页定位数据。', '按页面提示保存、提交或完成流程节点。'],
    role: '菜单和按钮按账号角色及模块权限动态显示。',
  },
  {
    id: 'common',
    title: '通用列表与数据操作',
    summary: '所有业务表格采用统一的搜索、筛选、排序、分页和横向浏览规则。',
    logic: [
      '表头字段可点击排序；分页支持 10/20/50/100 条每页。',
      '表格超过内容区域时，只显示 Ant Design 自带的底部横向滚动条；拖动该滚动条即可访问屏幕外字段，ITOM 不再额外生成第二条悬浮滚动条。',
      '提供下载模板时，必须保持工作表名称、列名和隐藏校验列不变；导入失败会返回工作表、行号和原因。',
      '示例数据只用于字段说明，不能编辑或参与业务流转；系统管理员可明确删除。',
    ],
    steps: ['先输入关键字，再选择核心字段筛选。', '点击表头确认排序方向。', '选择每页条数并翻页查看完整结果。', '批量维护时下载最新模板、填写、导入并处理失败行。'],
  },
  {
    id: 'itsm',
    title: 'ITSM',
    summary: '管理服务请求、服务目录、配置项、SLA、事件、变更、问题、供应商、合同和知识。',
    logic: [
      '服务请求按登记、分派、处理、验收和关闭推进；处理人只处理当前节点。',
      '服务目录由目录和服务项两层组成，服务项状态分为上架和下架。',
      '服务项的服务对象可选全体员工或自定义范围；自定义范围从组织架构树勾选部门或在岗员工，保存时校验引用并展示可读摘要。业务用户门户和提交服务请求时均由后端再次校验范围，管理员及 IT 内部角色仍可查看完整目录。',
      '服务项绑定版本化动态表单、流程和派单规则；网页端与 Aily MCP 使用同一份表单定义和后端校验，历史工单保存创建时快照。',
      'SLA 根据服务项和优先级匹配响应/解决时限，并为服务看板和绩效提供取数。',
      '事件强调恢复，变更强调审批、实施和回退，问题强调根因和永久修复。',
    ],
    steps: [
      '服务请求：选择已上架且本人可申请的服务项，填写其已发布动态表单；提交后系统保存快照、启动绑定流程并自动派单，登记人最终验收并关闭。',
      '服务目录：维护搜索词、典型/排除场景、服务对象、流程和默认优先级；在“表单/派单”中用可视化设计器发布表单版本，并配置固定人员、用户组、轮询或人工队列派单。',
      'CMDB/SLA：维护配置项、关联服务和时限策略；每个配置项均配置技术负责人，应用配置项额外配置负责 Bug 确认与验证的产品经理，两者可为同一人。',
      '事件/变更/问题：打开详情，按流程图或右上角允许的按钮推进并填写说明。',
      '供应商/合同/知识库：维护基础资料、到期信息和可复用知识。',
    ],
    role: '业务用户通常只看到服务请求和知识库；ITSM 管理操作按权限开放。',
  },
  {
    id: 'projects',
    title: '项目管理',
    summary: '管理项目立项、组合目标与优先级、章程、里程碑、WBS 和交付进度。',
    logic: [
      '项目经理只能从数字化团队成员中选择。章程导入可解析目标、范围、组织、里程碑和 WBS 草稿。',
      'WBS 完成度提供 0%/50%/100% 预设，也支持填写 0–100% 自定义比例。',
      '父级设为 100% 会级联子级；修改子级后父级按直接子项平均值递归回算。项目进度按末级任务工期加权。',
      'WBS 支持冻结表头和前三列、列宽/行高调整以及底部横向滚动条。',
      '组合治理复用项目执行数据，维护目标贡献、五维证据评分、人工优先级、跨项目依赖、资源超配告警和不可变基线。',
      '项目经理提交本人项目材料，BM/PMO 评分，TM 维护资源，CIO 决策并发布基线；系统不会因冲突告警自动改排期。',
    ],
    steps: ['进入“项目管理 → 项目列表”，新建项目并填写经理、日期、预算、主要组合和描述。', '需要时上传章程并确认解析结果。', '在项目详情维护里程碑和 WBS。', '进入“项目组合 → 治理总览”维护目标、评分、优先级、依赖和资源承诺。', '处理全部待治理项目后由 CIO 发布组合基线。'],
  },
  {
    id: 'requirements',
    title: '需求管理',
    summary: '从需求登记到评审、方案评估、路由和验收形成闭环。',
    logic: [
      '需求总览负责登记、澄清和决议；任务跟踪负责拆分任务和执行进度；需求评分规则负责维度和权重。',
      '登记前必须至少存在一个已启用的业务域；网页和 Aily MCP 只使用真实业务域列表，列表为空时先由管理员完成配置。',
      '普通业务用户只看本人需求；BDO 在 ITOM 网页端还可查看其被配置为业务 BDO 的服务域全部需求，但 Aily/MCP 仍只看本人需求，且不会因此获得评审权限。',
      '开发任务清单显示登记人：网页直接登记取当前登录人员，需求转化取原需求登记人，项目/WBS 转化取项目经理，Bug 修复取 Bug 登记人。',
      '需求可转开发、转项目、暂缓或拒绝；节点处理人和知会人由流程定义决定。',
    ],
    steps: ['在需求总览登记需求并选择业务域。', '根据当前节点补充分析、方案和评审结论。', '在任务跟踪查看责任人、计划日期和完成情况。', '需要调整评价口径时，由管理员维护需求评分规则。'],
  },
  {
    id: 'team',
    title: '团队管理',
    summary: '覆盖团队总览、人效评分、岗位编制、学习成长、活动积分和团队文化。',
    logic: [
      '团队总览展示数字化团队人数、负载、培训、招聘和积分；面板布局按账号保存。',
      '人效评分默认由角色贡献 80% + 团队贡献 20% 组成；多人评审按配置权重汇总。',
      '外部原数据只允许录入 external_business_satisfaction，评价对象必须是业务服务域，作用于该域 IT 侧负责人（BM）和 IT BP，不作用于业务 BDO。',
      '学习任务记录目标、完成进度、佐证和说明，进度比例自动换算团队贡献积分。',
    ],
    steps: [
      '人效评分：先选择考核周期，再查看总览、计分规则、分级评审、外部原数据和最终结果。',
      '评分明细：点击员工进入详情，维护角色权重、评审人权重、各维度分数、理由和证据。',
      '岗位编制：在岗位定义/招聘需求标签页直接编辑或进入详情编辑，也可导出、下载模板、批量导入。',
      '学习成长：在培训提升登记活动，在学习任务填写本周期目标并保存进度。管理员、CIO 或登记人可编辑/删除培训；改主讲或参与人仅在当前未发布、未锁定周期重算积分。',
      '活动积分/团队文化：维护积分事项、愿景、年度目标和行为准则。',
    ],
    role: 'IT PMO 由 CIO 直接评价，但可作为项目经理虚拟团队负责人对 IT 项目经理初评。',
  },
  {
    id: 'process',
    title: '流程中心',
    summary: '管理员/CIO 定义流程，处理人和审批人按节点执行，系统自动同步单据状态。',
    logic: [
      '处理节点使用“完成此步骤”；审批节点支持“同意”和“驳回”。同意理由可选，驳回理由必填。',
      '知会节点只发送通知，不生成待办；未指派节点可由有权限的人员认领。',
      '当前待办处理人或管理员可将当前任务转派给另一名在岗且已开通 ITOM 的人员；转派不改变流程节点和业务状态，并保留审计、通知新处理人。',
      '存量单据使用创建时的流程快照，新发布版本只作用于新单据。',
    ],
    steps: ['在流程定义配置节点类型、处理人、知会人、角色和自动化等级。', '发布流程版本。', '在流程监控按类型、状态、当前节点和处理人定位运行中单据。', '进入详情完成、同意、驳回或认领操作。'],
  },
  {
    id: 'admin',
    title: '系统管理',
    summary: '维护组织、用户、权限、字典、状态机、集成、品牌和审计。',
    logic: [
      '组织管理维护部门树、人员主数据和业务服务域；数字化团队范围可组合部门与指定人员，并决定人员下拉和绩效对象。',
      '用户与组管理维护账号、角色、用户组、登录开通和初始密码。',
      '角色与权限按模块设置查看/新建/编辑/删除；admin 隐式全权，auditor 只读。',
      '系统集成统一配置飞书登录/组织同步、SMTP 和 AD/LDAP；Aily 通过独立 MCP Server 调用 ITOM 业务能力，不再经过飞书服务台。配置机器人凭据、Verification Token 与 Encrypt Key 后，解决确认、未解决原因和星级评价可使用飞书原生卡片；ITOM 会验签、映射点击人并执行同一领域校验。',
      '审计日志记录用户、权限、流程、绩效、外部原数据和品牌发布等关键操作。',
    ],
    steps: [
      '组织管理：同步组织架构后，选择数字化团队部门及需要额外纳入的具体人员；再创建业务服务域并选择服务部门。',
      '用户与组：关联人员、配置角色/用户组并审批飞书登录申请。',
      '角色与权限：维护角色定义、预分配规则和模块动作权限。',
      '系统集成：分别保存飞书登录/组织同步、SMTP、AD/LDAP 配置并执行连接测试；维护 Aily MCP 公网地址、身份参数、机器人凭据、卡片回调地址、Verification Token 与 Encrypt Key。',
      '界面与品牌：上传并裁剪 Logo，配置名称、主题、侧栏、公告和默认首页。',
      '审计日志：按实体、动作、操作人和时间检索变更。',
    ],
    role: '系统管理页面大多仅对 admin 开放；CIO/负责人可访问的绩效、组织或岗位功能由权限矩阵决定。',
  },
  {
    id: 'profile',
    title: '个人中心与问题排查',
    summary: '个人中心管理账号偏好；遇到问题时按数据范围、权限、流程和模板顺序排查。',
    logic: [
      '个人中心支持基本信息、安全设置、通知偏好、操作记录、飞书绑定、主题和内容密度。',
      '密码修改后，管理员保存的初始密码密文会被清除；个人只能查看自己的操作记录。',
    ],
    steps: ['看不到菜单/人员：确认角色、模块权限和数字化团队范围，重新登录刷新。', '流程按钮不可用：确认当前节点处理人、认领状态、终态和流程版本。', '导入报错：重新下载最新模板，保持工作表/列名，按返回行号修正。', '评分不变化：确认重新取数、外部业务域、学习任务保存和周期发布状态。'],
  },
];

const EN_SECTIONS: ManualSection[] = [
  {
    id: 'overview', title: 'Platform overview', summary: 'ITOM unifies IT services, projects, requirements, team capability, and workflow governance.',
    logic: ['Business domains are horizontal service lines; user groups are vertical professional pools.', 'All person selectors use the administrator-defined digital-team scope.', 'The Dashboard splits service requests, changes, incidents, and problems into four independent cards, each showing its open/in-progress count and P1–P4 priority distribution; cross-module ITSM totals are not duplicated.', 'Service requests, incidents, changes, problems, requirements, and projects are workflow-driven.', 'Performance runs by assessment period and combines role, team, external-satisfaction, and learning inputs.'],
    steps: ['Sign in and confirm the account/role at the top right.', 'Open a permitted module from the left navigation.', 'Use search, filters, sortable headers, and pagination.', 'Save, submit, or complete the current action as prompted.'],
    role: 'Menus and actions are filtered by role and module permissions.',
  },
  {
    id: 'common', title: 'Common list and data actions', summary: 'Business tables share search, filters, sorting, pagination, and horizontal browsing.',
    logic: ['Headers sort ascending/descending; page sizes are 10/20/50/100.', 'Wide tables normally retain one ITOM-managed bottom scrollbar and a visible header; duplicate scrollbars are hidden only after it is usable, with a native scrollbar retained as fallback.', 'Use the latest downloaded template without changing sheet names, columns, or validation columns.', 'Example rows are read-only and can be deleted by administrators.'],
    steps: ['Search by keyword.', 'Apply a core-field filter.', 'Click a header to sort.', 'For bulk work, download, fill, import, and fix rejected rows.'],
  },
  {
    id: 'itsm', title: 'ITSM', summary: 'Manage requests, catalog, CMDB, SLA, incidents, changes, problems, vendors, contracts, and knowledge.',
    logic: ['Requests move through assignment, processing, acceptance, and closure.', 'Catalogs contain service items with published/unpublished status.', 'A service item audience is either all employees or a structured custom scope selected from departments and active employees; references are validated before save and enforced by both the requester portal and ticket-creation API.', 'Each item binds a versioned dynamic form, process, and dispatch rule; web and Aily MCP share one schema and backend validator, while historical tickets retain their creation snapshot.', 'SLA targets feed service dashboards and performance.', 'Incidents restore service; changes manage approval/implementation/rollback; problems manage root cause and permanent fixes.'],
    steps: ['Choose a published eligible item and complete its published dynamic form; ITOM stores a snapshot, starts the bound process, and dispatches the request.', 'Maintain search terms, typical/excluded scenarios, audience, process, and default priority; use Form / Dispatch to publish form versions and configure fixed-person, group, round-robin, or manual-queue dispatch.', 'Maintain CMDB and SLA data. Each CI has a technical owner; an Application additionally has the product manager who confirms and verifies its Bugs.', 'Process incident/change/problem records through their workflow.', 'Maintain vendors, contracts, and knowledge articles.'],
    role: 'Business users normally see requests and knowledge; ITSM maintenance is permission-controlled.',
  },
  {
    id: 'projects', title: 'Project management', summary: 'Manage charter, milestones, WBS, portfolio objectives and priority, and delivery progress.',
    logic: ['Project managers are selected from the digital team.', 'WBS supports presets and custom 0–100% progress.', 'Parent 100% cascades to descendants; child changes roll up by direct-child average; overall progress is leaf-task duration weighted.', 'WBS freezes the header and first three columns and supports resizing.', 'Portfolio governance reuses project facts and adds objective contributions, five-dimension evidence scoring, a human rank, cross-project dependencies, allocation-conflict warnings, and immutable baselines.', 'PM submits own-project material, BM/PMO scores, TM maintains resources, and CIO decides and publishes; warnings never auto-reschedule work.'],
    steps: ['Create a project with manager, dates, budget, one primary portfolio, and description.', 'Optionally upload a charter and confirm parsed content.', 'Maintain milestones and WBS in project detail.', 'Open Portfolio → Governance Overview to maintain objectives, scores, rank, dependencies, and commitments.', 'Resolve pending governance before CIO publishes a baseline.'],
  },
  {
    id: 'requirements', title: 'Requirement management', summary: 'Close the loop from registration and review through solution routing and acceptance.',
    logic: ['Overview handles registration and decisions; Task Tracking handles execution; Requirement Scoring Rules handles dimensions and weights.', 'At least one active business domain is required; the web UI and Aily MCP use only the live domain list and report an explicit blocker when it is empty.', 'A normal business user sees only own requirements. In the ITOM web module, a BDO additionally sees requirements in domains where that person is the configured business BDO; Aily/MCP remains owner-only and the wider view grants no review authority.', 'Development-task lists show the registrar: direct web registration uses the signed-in person, requirement conversion uses the original requirement requester, project/WBS conversion uses the project manager, and Bug repair uses the Bug reporter.', 'Requirements route to development, projects, deferment, or rejection through workflow.'],
    steps: ['Register a requirement and select its domain.', 'Add analysis, solution, and review results at the current step.', 'Track owners, dates, and completion in Task Tracking.', 'Maintain scoring rules when the evaluation model changes.'],
  },
  {
    id: 'team', title: 'Team management', summary: 'Team overview, performance, headcount, learning, points, and culture.',
    logic: ['Performance scoring defaults to 80% role contribution plus 20% team contribution.', 'Multi-evaluator scores are aggregated by configured evaluator weights.', 'External raw data accepts only external_business_satisfaction for a business domain.', 'Learning tasks record goals, progress, evidence, and notes; progress converts to team points.'],
    steps: ['Select an assessment period in Performance.', 'Open employee detail to maintain role/evaluator weights, scores, reasons, and evidence.', 'Maintain positions and hiring needs inline or in detail; export/import when needed.', 'Record training and learning tasks. Administrators, CIO, or the registrar may edit/delete training; changing host or participants re-awards points only in the current unpublished, unlocked period.', 'Maintain activity points and team charter.'],
    role: 'IT PMO is directly reviewed by CIO and can initially review IT project managers.',
  },
  {
    id: 'process', title: 'Process center', summary: 'Define workflows and monitor running records.',
    logic: ['Processing nodes use Complete Step; approval nodes support Approve and Reject.', 'Approval comments are optional; rejection reasons are mandatory.', 'The current pending handler or an administrator may reassign the current task to another active, in-position ITOM user without changing node or business state; the transfer is audited and notified.', 'CC recipients receive notifications without a task.', 'Existing records retain their creation-time process snapshot.'],
    steps: ['Configure node types, handlers, CC recipients, roles, and automation.', 'Publish the process version.', 'Filter running records in Process Monitor.', 'Complete, approve, reject, claim, or reassign the current action.'],
  },
  {
    id: 'admin', title: 'System administration', summary: 'Organization, users, permissions, dictionaries, integrations, branding, and audit.',
    logic: ['Organization scope controls every operational person selector.', 'Users/groups manage accounts, roles, resource pools, provisioning, and initial passwords.', 'System Integrations groups Feishu sign-in/organization sync, SMTP, and AD/LDAP; Aily uses the separate MCP Server instead of Feishu Helpdesk. Bot credentials plus the callback Verification Token and Encrypt Key enable native close/reopen/rating cards; ITOM verifies the signature and clicker identity before applying the same domain rules.', 'Branding controls login and post-login visual settings; audit records important changes.'],
    steps: ['Sync organization data, select digital-team departments, and add any individually included people.', 'Manage users/groups and approve Feishu provisioning.', 'Maintain roles, provisioning rules, and module actions.', 'Save/test Feishu sign-in/sync, SMTP, and AD/LDAP settings; maintain the Aily MCP public endpoint, identity parameters, bot credentials, card callback URL, Verification Token, and Encrypt Key.', 'Configure names, logos, theme, sidebar, announcements, and landing pages.', 'Search audit logs.'],
    role: 'Most system pages are admin-only; other access follows the permission matrix.',
  },
  {
    id: 'profile', title: 'Profile and troubleshooting', summary: 'Manage personal preferences and use a consistent diagnosis sequence.',
    logic: ['Profile includes basic information, security, notification preferences, activity, Feishu binding, theme, and density.', 'Changing the password clears the administrator-held initial-password ciphertext.'],
    steps: ['Missing menu/people: check role, module permission, and digital scope.', 'Disabled workflow action: check assignee, claim state, terminal state, and process version.', 'Import error: download a fresh template and preserve sheet/column names.', 'Unchanged score: recompute the period and verify external domain input, saved learning tasks, and publication state.'],
  },
];

const CATEGORY_META: Record<HelpCategoryId, { zh: string; en: string; icon: React.ReactNode }> = {
  'getting-started': { zh: '快速开始', en: 'Getting started', icon: <RocketOutlined /> },
  itsm: { zh: 'ITSM 服务管理', en: 'ITSM services', icon: <CustomerServiceOutlined /> },
  projects: { zh: '项目管理', en: 'Projects', icon: <ProjectOutlined /> },
  requirements: { zh: '需求管理', en: 'Requirements', icon: <AppstoreOutlined /> },
  team: { zh: '团队管理', en: 'Team management', icon: <TeamOutlined /> },
  process: { zh: '流程中心', en: 'Process center', icon: <ApartmentOutlined /> },
  admin: { zh: '系统管理', en: 'Administration', icon: <SettingOutlined /> },
  profile: { zh: '个人中心与排障', en: 'Profile & troubleshooting', icon: <InfoCircleOutlined /> },
};

const ARTICLE_META: Record<string, { category: HelpCategoryId; tags: string[]; featured?: boolean }> = {
  overview: { category: 'getting-started', tags: ['平台介绍', '权限'], featured: true },
  common: { category: 'getting-started', tags: ['搜索', '导入导出', '表格'], featured: true },
  itsm: { category: 'itsm', tags: ['服务请求', '服务目录', 'SLA'], featured: true },
  projects: { category: 'projects', tags: ['项目', 'WBS', '进度'], featured: true },
  requirements: { category: 'requirements', tags: ['需求', '评审', '任务'], featured: true },
  team: { category: 'team', tags: ['人效评分', '岗位', '学习成长'], featured: true },
  process: { category: 'process', tags: ['审批', '处理节点', '驳回'], featured: false },
  admin: { category: 'admin', tags: ['组织', '权限', '集成'], featured: false },
  profile: { category: 'profile', tags: ['账户', '主题', '排障'], featured: false },
};

const CATEGORY_ORDER: HelpCategoryId[] = ['getting-started', 'itsm', 'projects', 'requirements', 'team', 'process', 'admin', 'profile'];

function buildDetailedArticles(english: boolean): HelpArticle[] {
  const updated = english ? 'Updated Jul 29, 2026' : '更新于 2026-07-29';
  if (english) {
    return [
      {
        id: 'itsm-service-request-flow', category: 'itsm', title: 'Service request: from submission to closure',
        summary: 'Understand the complete request lifecycle, ownership hand-offs, acceptance, SLA capture, and closure rules.',
        tags: ['Request', 'Workflow', 'SLA'], updated,
        logic: [
          'Entry: a requester selects a published eligible service item and completes its currently published dynamic form; the same schema and validator are used by the web UI and Aily MCP.',
          'Assignment: ITOM stores the form version/schema snapshot, creates the request number and SLA clock, starts the process bound to the item, and applies item, catalog, then global dispatch rules.',
          'Processing: the handler records analysis, solution, and delivery evidence, then completes the current processing node. A clarification returns to the active step instead of bypassing the workflow.',
          'Acceptance: the requester checks the delivered result. Acceptance moves the record to closure; rejection returns it to processing with the acceptance comment retained.',
          'Closure: the system stamps completion time, SLA result, audit event, and performance inputs. Reopening is restricted to the configured permission scope.',
        ],
        steps: [
          'Open ITSM → Service Requests and click New.',
          'Choose a published service item, confirm priority/SLA, and complete only the fields required by its dynamic form.',
          'Use Current Step or My Turn to locate the task; the assignee completes the node with a processing note.',
          'The requester reviews the result and accepts or returns it with a reason.',
          'After closure, use the audit trail and SLA details to confirm the hand-off was captured.',
        ],
        role: 'Requesters submit and accept. IT handlers process the current node. The current pending handler or an administrator may reassign the task to an eligible active ITOM user; reopen remains permission-controlled.',
      },
      {
        id: 'itsm-change-flow', category: 'itsm', title: 'Change management: assess, approve, implement, and verify',
        summary: 'A change is not just a status update: risk, approval, implementation evidence, validation, and rollback must form one traceable chain.',
        tags: ['Change', 'Approval', 'Rollback'], updated,
        logic: [
          'Request: the initiator describes scope, affected services/configuration items, planned window, risk, validation, and rollback plan.',
          'Assessment: the change owner confirms impact and risk. Required approvers and CC recipients are resolved by the published process version.',
          'Approval: approval nodes expose Approve and Reject. Approval comments are optional; a rejection reason is required and returns the change to the configured correction step.',
          'Implementation: after approval, the implementer executes in the window and records start/end, evidence, actual impact, and any deviation.',
          'Verification and closure: the owner confirms service health and acceptance criteria. A failed verification triggers rollback or an incident link before closure.',
        ],
        steps: [
          'Create a change and complete the risk, window, validation, and rollback fields.',
          'Open the process detail to identify the current approver or handler; do not edit a later-stage field to bypass the node.',
          'Approvers select Approve or Reject in the top-right action area and provide a reason when rejecting.',
          'The implementer records execution evidence and completes the processing step.',
          'Verify the service, attach the result, and close only after the acceptance criteria pass.',
        ],
        role: 'The initiator owns the plan, approvers make the risk decision, and the implementer owns execution evidence. The process configuration controls who may act at each node.',
      },
      {
        id: 'requirements-lifecycle', category: 'requirements', title: 'Requirement lifecycle: register, evaluate, route, and deliver',
        summary: 'See how a requirement moves from an idea to a decision, delivery task, acceptance, and hand-off.',
        tags: ['Requirement', 'Review', 'Decision'], updated,
        logic: [
          'Register: the requester records the problem, expected value, business domain, priority, and acceptance expectation.',
          'Clarify and score: IT clarifies scope and dependency, then applies the configured scoring dimensions and weights to establish priority and confidence.',
          'Review: the responsible line confirms feasibility, estimate, risk, and solution direction. Approval nodes require an explicit decision; a rejection keeps the reason.',
          'Route: an accepted requirement is routed to a project, development work, or another delivery path. Deferred and rejected outcomes remain searchable with their decisions.',
          'Deliver and close: task completion, acceptance evidence, and knowledge hand-off are checked before the requirement reaches its terminal state.',
        ],
        steps: [
          'Open Requirements → Overview and create the requirement with its business domain.',
          'Complete clarification, scoring, dependencies, and solution assessment at the current step.',
          'Use the process action to approve, reject, or complete the review; do not treat a comment as an approval.',
          'If approved, confirm the linked project/task owner and planned dates in Task Tracking.',
          'Attach acceptance evidence and close after the business owner confirms the outcome.',
        ],
        role: 'Business requesters define value and acceptance. IT business/professional owners clarify and assess. CIO/approvers make the configured decision. Delivery owners close the hand-off.',
      },
      {
        id: 'project-delivery-flow', category: 'projects', title: 'Project delivery: charter to closure',
        summary: 'Follow the project control loop from charter confirmation through WBS execution, progress roll-up, change control, and retrospective.',
        tags: ['Project', 'WBS', 'Delivery'], updated,
        logic: [
          'Initiation: a project is created manually or from a charter import. Manager, dates, budget, scope, risks, and stakeholders must be confirmed before launch.',
          'Planning: milestones and hierarchical WBS tasks define deliverables, owners, dependencies, acceptance criteria, and planned dates.',
          'Execution monitoring: task progress, overdue dates, risks, and actual results are updated by the task owner; project progress rolls up from leaf tasks using duration weighting.',
          'Change control: scope/date/budget changes are recorded as decisions with impact and approval rather than silently overwriting the baseline.',
          'Closure: the manager confirms deliverables, acceptance, open risks, lessons learned, and hand-off; the retrospective completes the project flow.',
        ],
        steps: [
          'Create the project or upload a charter, then review the parsed organization, milestones, and WBS draft.',
          'Confirm the digital-team project manager, baseline dates, budget, scope, and acceptance criteria.',
          'Maintain WBS progress using the preset or a 0–100% value; update evidence and actual dates at the task level.',
          'Review the project health/progress view and raise a change decision when the baseline must move.',
          'Complete acceptance, hand-off, and closure review; do not close while required child tasks remain open.',
        ],
        role: 'The project manager owns the baseline and closure. Task owners update execution. PMO monitors delivery quality. CIO/portfolio roles approve configured baseline changes.',
      },
      {
        id: 'project-wbs-progress', category: 'projects', title: 'WBS progress: parent-child roll-up rules',
        summary: 'Learn why a parent task changes when child tasks change and how the project percentage is calculated.',
        tags: ['WBS', 'Progress', 'Roll-up'], updated,
        logic: [
          'WBS numbering represents hierarchy: a parent summarizes its direct children, while a leaf task holds the actual execution progress.',
          'Setting a parent to 100% is an explicit completion decision and cascades 100% to every descendant.',
          'When a child is edited, the parent is recalculated from the average of its direct children; the rule applies recursively up the tree.',
          'Overall project progress is calculated from leaf-task progress weighted by planned duration, not from the number of rows.',
        ],
        steps: [
          'Use the progress field to choose 0%, 50%, 100%, or enter a custom integer from 0 to 100.',
          'Set a parent to 100% only when the complete work package is finished.',
          'For partial delivery, update each child and let the parent roll up automatically.',
          'Check the WBS table with the frozen header/first three columns and bottom scrollbar before saving.',
        ],
        role: 'Task owners maintain leaf progress. Project managers verify parent roll-up and baseline impact.',
      },
    ];
  }
  return [
    {
      id: 'itsm-service-request-flow', category: 'itsm', title: '服务请求：从提交到关闭',
      summary: '讲清服务请求的完整生命周期、责任交接、验收、SLA 取数与关闭规则。',
      tags: ['服务请求', '流程', 'SLA'], updated,
      logic: [
        '入口：业务用户选择本人可申请的已上架服务项，填写其当前已发布动态表单；网页端与 Aily MCP 使用同一份定义和校验。',
        '分派：系统保存表单版本与定义快照、生成编号和 SLA 计时、启动服务项绑定流程，并依次应用服务项、目录和全局派单规则。',
        '处理：处理人记录分析、方案和交付佐证，然后完成当前处理节点；需要澄清时回到当前处理步骤，不绕过流程直接改终态。',
        '验收：登记人检查交付结果；通过后进入关闭，拒绝则带着验收意见回到处理节点。',
        '关闭：系统写入实际完成时间、SLA 结果、审计事件和绩效取数；重开仅对配置范围内的角色开放。',
      ],
      steps: [
        '进入“ITSM → 服务请求”，点击新建。',
        '选择已上架服务项，确认优先级/SLA，只填写该动态表单要求的字段。',
        '通过“当前节点”或“待我处理”定位待办，处理人填写处理说明并完成节点。',
        '登记人查看交付结果，选择验收通过或带理由退回。',
        '关闭后查看审计轨迹和 SLA 明细，确认责任交接已留痕。',
      ],
      role: '业务用户负责提交和验收；IT 处理人负责当前节点。当前待办处理人或管理员可转派给符合条件的在岗 ITOM 用户；重开仍按权限矩阵控制。',
    },
    {
      id: 'itsm-change-flow', category: 'itsm', title: '变更管理：评估、审批、实施、验证',
      summary: '变更不是简单改状态，风险、审批、实施证据、验证和回退必须形成一条可追溯链路。',
      tags: ['变更', '审批', '回退'], updated,
      logic: [
        '申请：发起人填写范围、受影响服务/配置项、计划窗口、风险、验证标准和回退方案。',
        '评估：变更负责人确认影响和风险；审批人和知会人由已发布的流程版本解析。',
        '审批：审批节点提供“同意”和“驳回”；同意理由可选，驳回理由必填并返回配置的整改节点。',
        '实施：审批通过后由实施人按计划窗口执行，记录开始/结束时间、证据、实际影响和偏差。',
        '验证与关闭：负责人确认服务健康和验收标准；验证失败时先回退或关联事件，再进入关闭。',
      ],
      steps: [
        '新建变更，完整填写风险、窗口、验证和回退字段。',
        '在流程详情确认当前审批人/处理人，不通过修改后续字段绕过当前节点。',
        '审批人从右上角选择“同意”或“驳回”，驳回时填写原因。',
        '实施人记录执行证据并完成处理节点。',
        '验证服务并上传结果，验收标准通过后再关闭。',
      ],
      role: '发起人负责方案，审批人负责风险决策，实施人负责执行证据；每个节点的可操作人由流程配置决定。',
    },
    {
      id: 'requirements-lifecycle', category: 'requirements', title: '需求生命周期：登记、评估、路由与交付',
      summary: '说明需求如何从想法进入决策，再进入开发/项目交付，最后完成验收和交接。',
      tags: ['需求', '评审', '决策'], updated,
      logic: [
        '登记：申请人记录问题、期望价值、业务域、优先级和验收预期。',
        '澄清与评分：IT 补充范围、依赖和约束，按已配置的评分维度与权重形成优先级和信心度。',
        '评审：责任专业线确认可行性、估算、风险和方案方向；审批节点必须产生明确决定，拒绝原因会保留。',
        '路由：通过的需求进入项目、开发任务或其他交付路径；暂缓和拒绝结果仍可搜索并保留决策。',
        '交付与关闭：任务完成、验收证据和知识交接全部确认后，需求才进入终态。',
      ],
      steps: [
        '进入“需求管理 → 需求总览”，新建需求并选择业务域。',
        '在当前节点补充澄清、评分、依赖、方案和评审信息。',
        '使用流程按钮同意、驳回或完成评审；评论不等于审批结果。',
        '通过后在任务跟踪确认关联项目/任务、负责人和计划日期。',
        '业务负责人确认结果并补充验收佐证后关闭。',
      ],
      role: '业务申请人定义价值和验收；IT BP/专业线负责人负责澄清评估；CIO/审批人作配置范围内的决策；交付负责人完成交接。',
    },
    {
      id: 'project-delivery-flow', category: 'projects', title: '项目交付：从章程到收尾',
      summary: '跟随项目从章程确认、WBS 执行、进度汇总、变更控制到复盘收尾的完整控制环。',
      tags: ['项目', 'WBS', '交付'], updated,
      logic: [
        '立项：项目可手工创建或由章程导入，启动前必须确认经理、日期、预算、范围、风险和干系人。',
        '计划：里程碑和分级 WBS 定义交付物、责任人、前置依赖、验收标准和计划日期。',
        '执行监控：任务负责人更新进度、逾期和实际结果；项目进度按末级任务计划工期加权汇总。',
        '变更控制：范围、日期、预算发生变化时，以变更决议记录影响和审批，不能静默覆盖基线。',
        '收尾：项目经理确认交付、验收、遗留风险、经验教训和交接；复盘完成后流程才结束。',
      ],
      steps: [
        '新建项目或上传章程，检查解析出的组织、里程碑和 WBS 草稿。',
        '确认数字化团队范围内的项目经理、基线日期、预算、范围和验收标准。',
        '在任务级维护 WBS 进度，填写实际日期和交付佐证。',
        '查看项目健康度/进度，基线必须变化时发起变更决议。',
        '完成验收、交接和收尾复盘；子任务未完成时不能直接关闭项目。',
      ],
      role: '项目经理负责基线和收尾；任务负责人更新执行；PMO 监控交付质量；CIO/组合角色审批配置范围内的基线变更。',
    },
    {
      id: 'project-wbs-progress', category: 'projects', title: 'WBS 进度：父子级自动汇总规则',
      summary: '解释为什么子任务变化会影响父级，以及项目完成比例如何计算。',
      tags: ['WBS', '进度', '汇总'], updated,
      logic: [
        'WBS 编号代表层级：父级概括直接子项，末级任务承载实际执行进度。',
        '将父级明确设为 100% 表示整个工作包完成，并向所有后代级联 100%。',
        '子级修改后，父级按直接子项平均值重新计算，并递归向上汇总。',
        '项目总进度按末级任务进度和计划工期加权，而不是按表格行数平均。',
      ],
      steps: [
        '完成度可选择 0%、50%、100%，也可填写 0–100 的整数。',
        '只有整个工作包完成时才把父级设置为 100%。',
        '部分完成时逐一填写子级，让父级自动汇总。',
        '保存前使用冻结的表头/前三列和底部滚动条检查完整字段。',
      ],
      role: '任务负责人维护末级进度，项目经理核对父级汇总和基线影响。',
    },
  ];
}

function buildArticles(sections: ManualSection[], english: boolean): HelpArticle[] {
  const baseArticles = sections.map((section, index) => ({
    ...section,
    ...ARTICLE_META[section.id],
    updated: english ? 'Updated Jul 23, 2026' : '更新于 2026-07-23',
    tags: english
      ? ARTICLE_META[section.id].tags.map((tag) => ({
        平台介绍: 'Platform', 权限: 'Permissions', 搜索: 'Search', 导入导出: 'Import/Export', 表格: 'Tables', 服务请求: 'Requests', 服务目录: 'Catalog', SLA: 'SLA', 项目: 'Projects', WBS: 'WBS', 进度: 'Progress', 需求: 'Requirements', 评审: 'Review', 任务: 'Tasks', 人效评分: 'Performance', 岗位: 'Positions', 学习成长: 'Learning', 审批: 'Approval', 处理节点: 'Processing', 驳回: 'Reject', 组织: 'Organization', 集成: 'Integrations', 账户: 'Account', 主题: 'Theme', 排障: 'Troubleshooting',
      } as Record<string, string>)[tag] ?? tag) : ARTICLE_META[section.id].tags,
    featured: ARTICLE_META[section.id].featured ?? index < 4,
  }));
  return [...baseArticles, ...buildDetailedArticles(english)];
}

function ArticleCard({ article, english, onOpen }: { article: HelpArticle; english: boolean; onOpen: () => void }) {
  const category = CATEGORY_META[article.category];
  return (
    <Card className="help-article-card" hoverable onClick={onOpen} role="button" tabIndex={0} onKeyDown={(event) => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onOpen(); }
    }}>
      <div className="help-article-card__topline">
        <Tag color="blue">{english ? category.en : category.zh}</Tag>
        <Text type="secondary">{article.updated}</Text>
      </div>
      <Title level={4}>{article.title}</Title>
      <Paragraph ellipsis={{ rows: 2 }} className="help-article-card__summary">{article.summary}</Paragraph>
      <div className="help-article-card__footer">
        <Space size={6} wrap>{article.tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}</Space>
        <RightOutlined className="help-article-card__arrow" aria-hidden="true" />
      </div>
    </Card>
  );
}

export default function UserManual() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const lang = useLangStore((state) => state.lang);
  const english = lang === 'en';
  const sections = useMemo(() => buildArticles(english ? EN_SECTIONS : ZH_SECTIONS, english), [english]);
  const [query, setQuery] = useState(searchParams.get('q') ?? '');
  const [category, setCategory] = useState<HelpCategoryId | 'all'>((searchParams.get('category') as HelpCategoryId | null) ?? 'all');
  const articleId = searchParams.get('article');
  const selectedArticle = sections.find((article) => article.id === articleId);
  const title = english ? 'ITOM Help Center' : 'ITOM 帮助中心';
  const searchPlaceholder = english ? 'Search products, features, questions, or keywords' : '搜索产品、功能、问题或关键词';
  const categoryLabel = (id: HelpCategoryId) => english ? CATEGORY_META[id].en : CATEGORY_META[id].zh;

  useEffect(() => {
    setQuery(searchParams.get('q') ?? '');
    setCategory((searchParams.get('category') as HelpCategoryId | null) ?? 'all');
  }, [searchParams]);

  const openArticle = (id: string) => setSearchParams({ article: id });
  const goHelpHome = () => {
    setQuery('');
    setCategory('all');
    setSearchParams({});
  };
  const goCategoryHome = (id: HelpCategoryId) => {
    setQuery('');
    setCategory(id);
    setSearchParams({ category: id });
  };
  const runSearch = (value: string) => {
    setQuery(value);
    setSearchParams(value.trim() ? { q: value.trim(), ...(category !== 'all' ? { category } : {}) } : (category !== 'all' ? { category } : {}));
  };
  const chooseCategory = (next: HelpCategoryId | 'all') => {
    setCategory(next);
    setSearchParams(query.trim() ? { q: query.trim(), ...(next !== 'all' ? { category: next } : {}) } : (next !== 'all' ? { category: next } : {}));
  };

  const filteredArticles = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return sections.filter((article) => {
      const matchesCategory = category === 'all' || article.category === category;
      if (!matchesCategory) return false;
      if (!normalized) return true;
      const haystack = [article.title, article.summary, article.tags.join(' '), article.logic.join(' '), article.steps.join(' ')].join(' ').toLowerCase();
      return haystack.includes(normalized);
    });
  }, [category, query, sections]);

  const popular = sections.filter((article) => article.featured).slice(0, 4);
  const recent = sections.slice().reverse().slice(0, 4);
  const quickLinks: Array<{ id: HelpCategoryId; description: string }> = [
    { id: 'getting-started', description: english ? 'Learn the platform in five minutes' : '五分钟了解平台与通用操作' },
    { id: 'itsm', description: english ? 'Requests, catalog, incidents, and changes' : '服务请求、目录、事件和变更' },
    { id: 'projects', description: english ? 'Charter, milestones, WBS, and progress' : '章程、里程碑、WBS 与进度' },
    { id: 'team', description: english ? 'Performance, positions, and learning' : '人效评分、岗位和学习成长' },
  ];

  if (selectedArticle) {
    const category = CATEGORY_META[selectedArticle.category];
    return (
      <div className="help-center-page">
        <div className="help-center-detail-head">
          <Breadcrumb items={[
            { title: <Button type="link" className="help-breadcrumb-link" onClick={goHelpHome}>{title}</Button> },
            { title: <Button type="link" className="help-breadcrumb-link" onClick={() => goCategoryHome(selectedArticle.category)}>{english ? category.en : category.zh}</Button> },
            { title: selectedArticle.title },
          ]} />
          <Button icon={<ArrowLeftOutlined />} onClick={() => goCategoryHome(selectedArticle.category)}>{english ? 'Back to product' : '返回模块主页'}</Button>
        </div>
        <Row gutter={[28, 28]} className="help-center-detail">
          <Col xs={24} xl={17}>
            <article className="help-article-detail">
              <div className="help-article-detail__meta"><Tag color="blue">{english ? category.en : category.zh}</Tag><Text type="secondary">{selectedArticle.updated}</Text></div>
              <Title level={1}>{selectedArticle.title}</Title>
              <Paragraph className="help-article-detail__summary">{selectedArticle.summary}</Paragraph>
              <Alert type="info" showIcon icon={<InfoCircleOutlined />} message={english ? 'This article reflects the current ITOM release. Your available actions still depend on role and module permissions.' : '本文基于当前 ITOM 版本编写。实际可见页面和操作按钮仍取决于账号角色及模块权限。'} />
              <section id={`${selectedArticle.id}-logic`} className="help-article-detail__section">
                <Title level={3}>{english ? 'How it works' : '运作逻辑'}</Title>
                <List size="small" dataSource={selectedArticle.logic} renderItem={(item) => <List.Item><Space align="start"><CheckCircleOutlined className="help-article-check" /><span>{item}</span></Space></List.Item>} />
              </section>
              <section id={`${selectedArticle.id}-steps`} className="help-article-detail__section">
                <Title level={3}>{english ? 'How to operate' : '操作步骤'}</Title>
                <List size="small" dataSource={selectedArticle.steps} renderItem={(item, index) => <List.Item><Space align="start"><Tag color="blue">{index + 1}</Tag><span>{item}</span></Space></List.Item>} />
              </section>
              {selectedArticle.role && <section id={`${selectedArticle.id}-role`} className="help-article-detail__section"><Alert type="warning" showIcon message={english ? 'Role boundary' : '角色边界'} description={selectedArticle.role} /></section>}
              <div className="help-article-detail__tags"><Space size={6} wrap>{selectedArticle.tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}</Space></div>
            </article>
          </Col>
          <Col xs={24} xl={7}>
            <Card className="help-article-toc" title={english ? 'On this page' : '本文目录'}>
              <Anchor affix={false} items={[
                { key: 'logic', href: `#${selectedArticle.id}-logic`, title: english ? 'How it works' : '运作逻辑' },
                { key: 'steps', href: `#${selectedArticle.id}-steps`, title: english ? 'How to operate' : '操作步骤' },
                ...(selectedArticle.role ? [{ key: 'role', href: `#${selectedArticle.id}-role`, title: english ? 'Role boundary' : '角色边界' }] : []),
              ]} />
            </Card>
            <Card className="help-article-toc help-article-toc--related" title={english ? 'Related articles' : '相关文档'}>
              <List size="small" dataSource={sections.filter((article) => article.category === selectedArticle.category && article.id !== selectedArticle.id).slice(0, 4)} renderItem={(article) => <List.Item><Button type="link" onClick={() => openArticle(article.id)}>{article.title}</Button></List.Item>} />
            </Card>
          </Col>
        </Row>
      </div>
    );
  }

  const noResults = query.trim() && filteredArticles.length === 0;
  return (
    <div className="help-center-page">
      <section className="help-center-hero">
        <div className="help-center-hero__eyebrow"><BookOutlined /> {english ? 'Product documentation' : '产品文档与使用指南'}</div>
        <Title level={1}>{english ? 'How can we help?' : '有什么可以帮助您？'}</Title>
        <Paragraph>{english ? 'Find task guides, module rules, and troubleshooting answers for the ITOM platform.' : '按产品、任务或问题查找 ITOM 的操作指南、运作规则和排障答案。'}</Paragraph>
        <Input.Search
          className="help-center-search"
          size="large"
          allowClear
          enterButton={<><SearchOutlined /> {english ? 'Search' : '搜索'}</>}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onSearch={runSearch}
          placeholder={searchPlaceholder}
          aria-label={searchPlaceholder}
        />
        <div className="help-center-hero__hint"><SearchOutlined /> {english ? 'Search by module name, action, field, or error message' : '可搜索模块名称、操作动作、字段名称或错误提示'}</div>
      </section>

      <section className="help-quick-links" aria-label={english ? 'Quick links' : '快捷入口'}>
        {quickLinks.map((link) => (
          <Card key={link.id} className="help-quick-link" hoverable onClick={() => chooseCategory(link.id)}>
            <div className="help-quick-link__icon">{CATEGORY_META[link.id].icon}</div>
            <div><Text strong>{categoryLabel(link.id)}</Text><Paragraph ellipsis={{ rows: 1 }}>{link.description}</Paragraph></div>
            <RightOutlined />
          </Card>
        ))}
      </section>

      <div className="help-center-body">
        <aside className="help-category-nav" aria-label={english ? 'Product categories' : '产品分类'}>
          <Card title={english ? 'Browse by product' : '按产品浏览'}>
            <button type="button" className={`help-category-item ${category === 'all' ? 'is-active' : ''}`} onClick={() => chooseCategory('all')}><AppstoreOutlined /><span>{english ? 'All documentation' : '全部文档'}</span><Text type="secondary">{sections.length}</Text></button>
            {CATEGORY_ORDER.map((id) => <button type="button" key={id} className={`help-category-item ${category === id ? 'is-active' : ''}`} onClick={() => chooseCategory(id)}>{CATEGORY_META[id].icon}<span>{categoryLabel(id)}</span><Text type="secondary">{sections.filter((article) => article.category === id).length}</Text></button>)}
          </Card>
          <Card className="help-category-note" size="small" title={english ? 'Need a quick answer?' : '需要快速定位？'}>
            <Text type="secondary">{english ? 'Start with Common list actions or search the exact field/error text.' : '先查看“通用列表与数据操作”，或直接搜索页面字段和错误提示。'}</Text>
          </Card>
        </aside>

        <main className="help-center-main">
          {noResults ? <Card><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={english ? 'No matching documents' : '没有找到匹配文档'}><Button type="primary" onClick={() => runSearch('')}>{english ? 'Clear search' : '清除搜索'}</Button></Empty></Card> : query.trim() || category !== 'all' ? (
            <section>
              <div className="help-section-heading"><div><Title level={2}>{query.trim() ? (english ? 'Search results' : '搜索结果') : categoryLabel(category as HelpCategoryId)}</Title><Text type="secondary">{english ? `${filteredArticles.length} documents` : `共 ${filteredArticles.length} 篇文档`}</Text></div></div>
              <div className="help-article-grid">{filteredArticles.map((article) => <ArticleCard key={article.id} article={article} english={english} onOpen={() => openArticle(article.id)} />)}</div>
            </section>
          ) : (
            <>
              <section>
                <div className="help-section-heading"><div><Title level={2}><FireOutlined /> {english ? 'Popular guides' : '热门指南'}</Title><Text type="secondary">{english ? 'Frequently used procedures and rules' : '最常用的操作流程与规则说明'}</Text></div><Button type="link" onClick={() => chooseCategory('all')}>{english ? 'View all' : '查看全部'} <RightOutlined /></Button></div>
                <div className="help-article-grid">{popular.map((article) => <ArticleCard key={article.id} article={article} english={english} onOpen={() => openArticle(article.id)} />)}</div>
              </section>
              <Row gutter={[20, 20]} className="help-lower-sections">
                <Col xs={24} lg={14}><Card title={<Space><ClockCircleOutlined />{english ? 'Recently updated' : '最近更新'}</Space>}><List dataSource={recent} renderItem={(article) => <List.Item actions={[<Button type="link" onClick={() => openArticle(article.id)}>{english ? 'Read' : '查看'}</Button>]}><List.Item.Meta avatar={CATEGORY_META[article.category].icon} title={article.title} description={article.summary} /></List.Item>} /></Card></Col>
                <Col xs={24} lg={10}><Card title={<Space><AppstoreOutlined />{english ? 'All products' : '全部产品模块'}</Space>}><div className="help-module-list">{CATEGORY_ORDER.map((id) => <Button key={id} type="text" onClick={() => chooseCategory(id)}>{CATEGORY_META[id].icon}<span>{categoryLabel(id)}</span><RightOutlined /></Button>)}</div></Card></Col>
              </Row>
            </>
          )}
        </main>
      </div>
      <div className="help-center-footer"><Text type="secondary">{english ? 'ITOM documentation follows the current product release and permission model.' : 'ITOM 文档与当前产品版本、权限模型同步维护。'}</Text><Button type="link" onClick={() => navigate(-1)}>{english ? 'Return to the previous page' : '返回上一页'}</Button></div>
    </div>
  );
}
