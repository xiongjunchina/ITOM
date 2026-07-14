/** process 域页面文案（M7 增量双语）。键名以 proc. 前缀，zh/en 成对补充；缺 key 回退中文。 */
import type { Dict } from '../dict';

export const zh: Dict = {
  // 流程定义：抽屉标题
  'proc.drawer.create': '新建流程',
  'proc.drawer.edit': '编辑流程',
  'proc.drawer.new-version': '另存新版本',

  // 流程定义：消息 / 提示
  'proc.stepAtLeastOne': '请至少配置一个步骤',
  'proc.triggerInvalid': '触发条件不是合法的 JSON 对象，请检查“高级 JSON”内容',
  'proc.created': '流程已创建',
  'proc.updated': '流程已更新',
  'proc.newVersionCreated': '新版本已创建，旧版本已停用',
  'proc.activated': '流程已激活',
  'proc.deactivated': '流程已停用',
  'proc.active': '激活',
  'proc.inactive': '停用',

  // 流程定义：卡片 / 列表
  'proc.title': '流程定义',
  'proc.group.itsmSr': 'ITSM（服务请求）',
  'proc.group.itsmChange': 'ITSM（变更）',
  'proc.group.itsmIncident': 'ITSM（事件）',
  'proc.group.itsmOther': '工单（其他）',
  'proc.deleteConfirm': '删除流程「{name}」？',
  'proc.deleteDesc': '仅未产生过实例且已停用的版本可删除；删除后不可恢复。',
  'proc.deleted': '流程已删除',
  'proc.emptyDefs': '暂无流程定义',
  'proc.instanceCount': '实例数：{n}',
  'proc.stepsLocked': '步骤已锁定',
  'proc.triggerLabel': '触发条件：',
  'proc.triggerNone': '（无）',

  // 流程定义：锁定步骤只读表列
  'proc.col.name': '名称',
  'proc.col.defaultAssign': '默认指派',
  'proc.col.cc': '知会人',
  'proc.col.autonomy': '自治级别',
  'proc.col.sla': 'SLA(小时)',
  'proc.col.desc': '说明',

  // 流程定义：抽屉告警
  'proc.lockedAlertMsg': '该流程已有 {n} 个实例，步骤已锁定',
  'proc.lockedAlertDesc': '如需调整步骤，请使用“另存新版本”。',
  'proc.newVersionAlert': '将基于 v{version} 创建新版本（code 自动变更，如 {code}@v{next}），并停用旧版本',

  // 流程定义：表单
  'proc.preview': '流程预览',
  'proc.basicInfo': '基本信息',
  'proc.code': '代码',
  'proc.codeRequired': '请输入流程代码',
  'proc.codePattern': '2-32 位小写字母、数字或下划线',
  'proc.codePlaceholder': '如 incident_std',
  'proc.name': '名称',
  'proc.nameRequired': '请输入流程名称',
  'proc.entityType': '单据类型',
  'proc.entityTypeRequired': '请选择单据类型',
  'proc.triggerTicketType': '触发条件（工单类型）',
  'proc.triggerTooltip': '选择后自动生成 {"ticket_type": ...}；留空表示不按工单类型过滤',
  'proc.triggerAny': '不限',
  'proc.advancedJson': '高级 JSON（触发条件，可直接编辑；留空 = 无条件）',
  'proc.advancedJsonPlaceholder': '如 {"ticket_type": "incident"}',
  'proc.desc': '描述',

  // 流程定义：步骤编辑
  'proc.stepDef': '步骤定义',
  'proc.stepNameRequired': '步骤名称必填',
  'proc.stepNamePlaceholder': '步骤名称',
  'proc.defaultAssignPlaceholder': '默认指派（角色/组）',
  'proc.required': '必选',
  'proc.autonomyPlaceholder': '自治级别',
  'proc.slaPlaceholder': 'SLA(h)',
  'proc.ccPlaceholder': '知会人（可多选，仅通知不产生任务）',
  'proc.stepDescPlaceholder': '说明',
  'proc.addStep': '添加步骤',
  'proc.stepHint':
    '步骤顺序即执行顺序（保存时自动按当前顺序编号）。自治级别：L1 全自动 ~ L4 纯人工。「知会人」在步骤激活时仅发送站内通知，不产生任务、不阻塞流程。',

  // 流程监控
  'proc.monitorTitle': '流程监控',
  'proc.col.definition': '流程名',
  'proc.col.entityType': '实体类型',
  'proc.col.currentStep': '当前步骤',
  'proc.col.currentAssignee': '当前处理人',
  'proc.col.dueAt': '截止时间',
  'proc.col.startedAt': '发起时间',
  'proc.col.completedAt': '完成时间',
  'proc.overdue': '已超时',
  'proc.totalN': '共 {n} 条',
};

export const en: Dict = {
  // Process definitions: drawer titles
  'proc.drawer.create': 'New Process',
  'proc.drawer.edit': 'Edit Process',
  'proc.drawer.new-version': 'Save as New Version',

  // Process definitions: messages
  'proc.stepAtLeastOne': 'Please configure at least one step',
  'proc.triggerInvalid': 'Trigger condition is not a valid JSON object; please check the "Advanced JSON" content',
  'proc.created': 'Process created',
  'proc.updated': 'Process updated',
  'proc.newVersionCreated': 'New version created; the old version has been deactivated',
  'proc.activated': 'Process activated',
  'proc.deactivated': 'Process deactivated',
  'proc.active': 'Active',
  'proc.inactive': 'Inactive',

  // Process definitions: card / list
  'proc.title': 'Process Definitions',
  'proc.group.itsmSr': 'ITSM (Service Request)',
  'proc.group.itsmChange': 'ITSM (Change)',
  'proc.group.itsmIncident': 'ITSM (Incident)',
  'proc.group.itsmOther': 'Ticket (Other)',
  'proc.deleteConfirm': 'Delete process "{name}"?',
  'proc.deleteDesc': 'Only deactivated versions with no instances can be deleted. This cannot be undone.',
  'proc.deleted': 'Process deleted',
  'proc.emptyDefs': 'No process definitions',
  'proc.instanceCount': 'Instances: {n}',
  'proc.stepsLocked': 'Steps locked',
  'proc.triggerLabel': 'Trigger: ',
  'proc.triggerNone': '(none)',

  // Process definitions: locked step table columns
  'proc.col.name': 'Name',
  'proc.col.defaultAssign': 'Default Assignee',
  'proc.col.cc': 'CC',
  'proc.col.autonomy': 'Autonomy',
  'proc.col.sla': 'SLA (hours)',
  'proc.col.desc': 'Description',

  // Process definitions: drawer alerts
  'proc.lockedAlertMsg': 'This process already has {n} instance(s); steps are locked',
  'proc.lockedAlertDesc': 'To adjust steps, use "Save as New Version".',
  'proc.newVersionAlert': 'A new version will be created from v{version} (code changes automatically, e.g. {code}@v{next}) and the old version deactivated',

  // Process definitions: form
  'proc.preview': 'Process Preview',
  'proc.basicInfo': 'Basic Info',
  'proc.code': 'Code',
  'proc.codeRequired': 'Please enter the process code',
  'proc.codePattern': '2-32 lowercase letters, digits or underscores',
  'proc.codePlaceholder': 'e.g. incident_std',
  'proc.name': 'Name',
  'proc.nameRequired': 'Please enter the process name',
  'proc.entityType': 'Entity Type',
  'proc.entityTypeRequired': 'Please select an entity type',
  'proc.triggerTicketType': 'Trigger (Ticket Type)',
  'proc.triggerTooltip': 'Selecting one auto-generates {"ticket_type": ...}; leave empty to not filter by ticket type',
  'proc.triggerAny': 'Any',
  'proc.advancedJson': 'Advanced JSON (trigger condition, editable directly; empty = no condition)',
  'proc.advancedJsonPlaceholder': 'e.g. {"ticket_type": "incident"}',
  'proc.desc': 'Description',

  // Process definitions: step editing
  'proc.stepDef': 'Step Definition',
  'proc.stepNameRequired': 'Step name is required',
  'proc.stepNamePlaceholder': 'Step name',
  'proc.defaultAssignPlaceholder': 'Default assignee (role/group)',
  'proc.required': 'Required',
  'proc.autonomyPlaceholder': 'Autonomy',
  'proc.slaPlaceholder': 'SLA(h)',
  'proc.ccPlaceholder': 'CC (multi-select; notify only, no task)',
  'proc.stepDescPlaceholder': 'Description',
  'proc.addStep': 'Add Step',
  'proc.stepHint':
    'Step order is the execution order (auto-numbered by current order on save). Autonomy: L1 fully automated ~ L4 manual. CC recipients only receive in-app notifications when a step activates; they create no task and do not block the process.',

  // Process monitor
  'proc.monitorTitle': 'Process Monitor',
  'proc.col.definition': 'Process',
  'proc.col.entityType': 'Entity Type',
  'proc.col.currentStep': 'Current Step',
  'proc.col.currentAssignee': 'Current Assignee',
  'proc.col.dueAt': 'Due At',
  'proc.col.startedAt': 'Started At',
  'proc.col.completedAt': 'Completed At',
  'proc.overdue': 'Overdue',
  'proc.totalN': '{n} total',
};
