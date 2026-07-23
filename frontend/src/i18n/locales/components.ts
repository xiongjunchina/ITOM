/** components 域文案（M7 增量双语）。键名以 comp. 前缀，zh/en 成对补充；缺 key 回退中文。 */
import type { Dict } from '../dict';

export const zh: Dict = {
  // 通用
  'comp.totalN': '共 {n} 条',
  'comp.listSep': '、',

  // WidgetBoard 自定义面板
  'comp.layoutSaved': '布局已保存',
  'comp.panelSaved': '面板配置已保存',
  'comp.customPanel': '自定义面板',
  'comp.keepOne': '至少保留一个板块',
  'comp.resetDefault': '恢复默认（全部显示）',

  // 甘特图
  'comp.gantt.empty': '暂无任务或里程碑，无法绘制甘特图',
  'comp.gantt.milestone': '里程碑（绿=达成 / 红=逾期）',
  'comp.gantt.today': '今日',
  'comp.gantt.depLine': '依赖线',
  'comp.gantt.task': '任务',
  'comp.gantt.milestoneCol': '里程碑',
  'comp.gantt.achieved': '已达成（{date}）',
  'comp.gantt.overdue': '已逾期',
  'comp.gantt.notAchieved': '未达成',

  // 批量导入
  'comp.import.downloadTemplate': '下载模板',
  'comp.import.batchImport': '批量导入',
  'comp.import.xlsxOnly': '仅支持 .xlsx 文件（请使用下载的模板填写）',
  'comp.import.successTitle': '导入成功',
  'comp.import.partialTitle': '导入完成（部分行失败）',
  'comp.import.gotIt': '知道了',
  'comp.import.col.sheet': '工作表',
  'comp.import.col.row': '行号',
  'comp.import.col.error': '失败原因',
  'comp.import.failedHint': '{n} 行未导入：失败行修正后可重新导入（已导入的行会自动跳过）',
  'comp.import.successN': '成功导入 {n} 条',
  'comp.import.itemN': '{label} {n} 条',
  'comp.import.successPrefix': '成功导入：',
  'comp.import.created.catalogs': '目录',
  'comp.import.created.items': '服务项',
  'comp.import.created.wbs': 'WBS 任务',
  'comp.import.created.milestones': '里程碑',

  // 流程示意图
  'comp.flow.noStep': '暂无步骤',
  'comp.flow.completeStep': '完成此步骤',
  'comp.flow.completeStepTitle': '完成步骤：{name}',
  'comp.flow.stepDone': '已完成，流程推进到下一步骤',
  'comp.flow.commentPlaceholder': '阶段结束说明（必填，≥5 字：结论/遗留/依据）',
  'comp.flow.commentRequired': '请填写阶段结束说明（至少 5 个字）',
  'comp.flow.unassigned': '未指派',
  'comp.flow.cc': '知会 {name}',
  'comp.flow.unnamed': '（未命名）',
  'comp.flow.approval': '审批',
  'comp.flow.approve': '同意',
  'comp.flow.reject': '驳回',
  'comp.flow.approveTitle': '审批同意',
  'comp.flow.approveCommentOptional': '同意理由（可选）',
  'comp.flow.rejectTitle': '驳回申请',
  'comp.flow.rejectReasonPlaceholder': '请填写驳回理由（至少 5 个字）',
  'comp.flow.rejectReasonRequired': '请填写驳回理由（至少 5 个字）',
  'comp.flow.approved': '已同意，流程推进到下一节点',
  'comp.flow.rejected': '已驳回流程申请',

  // 示例数据徽标 / 提示
  'comp.example.tip': '示例数据：字段内容即填写指引，仅供学习参考，不可编辑',
  'comp.example.tag': '示例',
  'comp.example.alert': '这是一条示例数据——每个字段的内容就是该字段的填写指引，仅供学习参考，不可编辑。',
};

export const en: Dict = {
  // Common
  'comp.totalN': '{n} total',
  'comp.listSep': ', ',

  // WidgetBoard customize panel
  'comp.layoutSaved': 'Layout saved',
  'comp.panelSaved': 'Panel settings saved',
  'comp.customPanel': 'Customize Panel',
  'comp.keepOne': 'Keep at least one panel',
  'comp.resetDefault': 'Reset to default (show all)',

  // Gantt chart
  'comp.gantt.empty': 'No tasks or milestones to render the Gantt chart',
  'comp.gantt.milestone': 'Milestone (green = achieved / red = overdue)',
  'comp.gantt.today': 'Today',
  'comp.gantt.depLine': 'Dependency',
  'comp.gantt.task': 'Task',
  'comp.gantt.milestoneCol': 'Milestone',
  'comp.gantt.achieved': 'Achieved ({date})',
  'comp.gantt.overdue': 'Overdue',
  'comp.gantt.notAchieved': 'Not achieved',

  // Batch import
  'comp.import.downloadTemplate': 'Download Template',
  'comp.import.batchImport': 'Batch Import',
  'comp.import.xlsxOnly': 'Only .xlsx files are supported (please use the downloaded template)',
  'comp.import.successTitle': 'Import Successful',
  'comp.import.partialTitle': 'Import Completed (some rows failed)',
  'comp.import.gotIt': 'Got it',
  'comp.import.col.sheet': 'Sheet',
  'comp.import.col.row': 'Row',
  'comp.import.col.error': 'Reason',
  'comp.import.failedHint': '{n} row(s) not imported: fix and re-import (already-imported rows are skipped automatically)',
  'comp.import.successN': 'Imported {n} rows',
  'comp.import.itemN': '{label}: {n}',
  'comp.import.successPrefix': 'Imported: ',
  'comp.import.created.catalogs': 'Catalogs',
  'comp.import.created.items': 'Service Items',
  'comp.import.created.wbs': 'WBS Tasks',
  'comp.import.created.milestones': 'Milestones',

  // Flow diagram
  'comp.flow.noStep': 'No steps',
  'comp.flow.completeStep': 'Complete Step',
  'comp.flow.completeStepTitle': 'Complete step: {name}',
  'comp.flow.stepDone': 'Done — process advanced to the next step',
  'comp.flow.commentPlaceholder': 'Stage completion notes (required, ≥5 chars: outcome / leftovers / basis)',
  'comp.flow.commentRequired': 'Please enter completion notes (at least 5 characters)',
  'comp.flow.unassigned': 'Unassigned',
  'comp.flow.cc': 'CC {name}',
  'comp.flow.unnamed': '(unnamed)',
  'comp.flow.approval': 'Approval',
  'comp.flow.approve': 'Approve',
  'comp.flow.reject': 'Reject',
  'comp.flow.approveTitle': 'Approve request',
  'comp.flow.approveCommentOptional': 'Approval comment (optional)',
  'comp.flow.rejectTitle': 'Reject request',
  'comp.flow.rejectReasonPlaceholder': 'Enter a rejection reason (at least 5 characters)',
  'comp.flow.rejectReasonRequired': 'Please enter a rejection reason (at least 5 characters)',
  'comp.flow.approved': 'Approved; the process advanced to the next step',
  'comp.flow.rejected': 'Process request rejected',

  // Example-data badge / notice
  'comp.example.tip': 'Example data: field content is the filling guidance, for reference only, not editable',
  'comp.example.tag': 'Example',
  'comp.example.alert': "This is example data — each field's content is the filling guidance for that field, for reference only and not editable.",
};
