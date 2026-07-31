import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Progress,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Switch,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  Upload,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import Table from '../../components/SortableTable';
import {
  ArrowLeftOutlined,
  DownloadOutlined,
  EditOutlined,
  PlusOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { api } from '../../api/client';
import { useGoBack } from '../../utils/nav';
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';
import { ExampleAlert } from '../../components/ExampleTag';
import DocumentTypeHint from '../../components/DocumentTypeHint';
import RecordRelationsPanel from '../../components/RecordRelationsPanel';
import { useAuthStore } from '../../stores/auth';
import { useRoleOptions } from '../../utils/roleOptions';
import FlowDiagram from '../../components/FlowDiagram';
import type { FlowDiagramStep } from '../../components/FlowDiagram';
import CompleteStepModal from '../../components/CompleteStepModal';
import ProcessActionButtons from '../../components/ProcessActionButtons';
import StickyTable from '../../components/StickyTable';
import GanttChart from '../../components/GanttChart';
import ImportButtons from '../../components/ImportButtons';
import ReasonModal from './ReasonModal';
import ProjectEditModal from './ProjectEditModal';
import type {
  AllowedTransition,
  AttachmentItem,
  CostEntry,
  Member,
  Milestone,
  MilestoneTrackingRow,
  ProjectDetail as ProjectDetailData,
  ProjectOrgEntry,
  Risk,
  RiskGrade,
  WbsStatus,
  WbsTask,
} from '../../api/types';
import { RISK_GRADES } from '../../api/types';
import { HealthDot, RiskLevelTag, StatusBadge, fmt10k, fmtPct } from './shared';

const WBS_TAG_COLORS: Record<WbsStatus, string> = {
  未开始: 'default',
  进行中: 'processing',
  已完成: 'success',
  已延期: 'error',
};

/** 进度偏差(天)着色单元：null→'-'，>0 红「+N」，<0 绿，0 灰 */
function renderDeviation(v: number | null | undefined): React.ReactNode {
  if (v == null) return '-';
  if (v > 0) return <span style={{ color: '#ff4d4f' }}>{`+${v}`}</span>;
  if (v < 0) return <span style={{ color: '#52c41a' }}>{v}</span>;
  return <span style={{ color: '#8c8c8c' }}>0</span>;
}

/** 状态 Tag（后端已算好，直接展示） */
function WbsStatusTag({ status, label }: { status: WbsStatus; label: string }): JSX.Element {
  return <Tag color={WBS_TAG_COLORS[status] ?? 'default'}>{label}</Tag>;
}

const WBS_PROGRESS_PRESETS = [0, 50, 100] as const;

/** WBS 完成度：提供常用预设，同时允许录入 0–100 的任意整数。 */
function WbsProgressEditor({
  value,
  onChange,
  customLabel,
  aggregateLabel,
  cascadeLabel,
  hasChildren = false,
}: {
  value: number;
  onChange: (value: number) => void;
  customLabel: string;
  aggregateLabel: string;
  cascadeLabel: string;
  hasChildren?: boolean;
}): JSX.Element {
  if (hasChildren) {
    return (
      <Select
        size="small"
        value="aggregate"
        style={{ width: 142 }}
        options={[
          { value: 'aggregate', label: `${value}% · ${aggregateLabel}` },
          { value: '100', label: cascadeLabel },
        ]}
        aria-label="父级完成度"
        onChange={(next: string) => {
          if (next === '100') onChange(100);
        }}
      />
    );
  }

  const isPreset = WBS_PROGRESS_PRESETS.includes(value as (typeof WBS_PROGRESS_PRESETS)[number]);
  const [customValue, setCustomValue] = useState(value);
  const [customMode, setCustomMode] = useState(!isPreset);

  useEffect(() => {
    setCustomValue(value);
    setCustomMode(!WBS_PROGRESS_PRESETS.includes(value as (typeof WBS_PROGRESS_PRESETS)[number]));
  }, [value]);

  const mode = customMode ? 'custom' : String(value);
  return (
    <Space size={4} wrap={false}>
      <Select
        size="small"
        value={mode}
        style={{ width: 76 }}
        options={[
          ...WBS_PROGRESS_PRESETS.map((p) => ({ value: String(p), label: `${p}%` })),
          { value: 'custom', label: customLabel },
        ]}
        aria-label="完成度预设"
        onChange={(next: string) => {
          if (next === 'custom') {
            setCustomValue(value);
            setCustomMode(true);
            return;
          }
          const parsed = Number(next);
          if (Number.isInteger(parsed)) {
            setCustomMode(false);
            onChange(Math.min(100, Math.max(0, parsed)));
          }
        }}
      />
      {mode === 'custom' && (
        <InputNumber
          size="small"
          value={customValue}
          style={{ width: 78 }}
          min={0}
          max={100}
          precision={0}
          formatter={(next) => `${next ?? ''}%`}
          parser={(next) => Number((next ?? '').replace('%', ''))}
          aria-label="自定义完成度"
          onChange={(next) => {
            if (next == null || !Number.isInteger(Number(next))) return;
            const normalized = Math.min(100, Math.max(0, Number(next)));
            setCustomValue(normalized);
            onChange(normalized);
          }}
        />
      )}
    </Space>
  );
}

function formatSize(size: number): string {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${size} B`;
}

/** 章程信息小节：加粗标题 + 内容（概述 tab 分段展示用） */
function CharterSection({ title, children }: { title: React.ReactNode; children: React.ReactNode }): JSX.Element {
  return (
    <div>
      <Typography.Text strong>{title}</Typography.Text>
      <div style={{ marginTop: 4 }}>{children}</div>
    </div>
  );
}

/** 章程多行文本：pre-wrap 保留换行，空显示 - */
function CharterText({ value }: { value: string | null | undefined }): JSX.Element {
  return value ? (
    <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>{value}</Typography.Paragraph>
  ) : (
    <Typography.Text type="secondary">-</Typography.Text>
  );
}

interface WbsNode extends WbsTask {
  children?: WbsNode[];
}

/** 平铺任务 → 树（孤儿节点归为根） */
function buildWbsTree(list: WbsTask[]): WbsNode[] {
  const ids = new Set(list.map((t) => t.id));
  const map = new Map<string, WbsNode>(list.map((t) => [t.id, { ...t }]));
  const roots: WbsNode[] = [];
  list.forEach((t) => {
    const node = map.get(t.id)!;
    const pid = t.parent_task_id && ids.has(t.parent_task_id) ? t.parent_task_id : null;
    if (pid) {
      const parent = map.get(pid)!;
      (parent.children ??= []).push(node);
    } else {
      roots.push(node);
    }
  });
  return roots;
}

export default function ProjectDetail() {
  const t = useT();
  const et = useEnums();
  const { id } = useParams<{ id: string }>();
  const goBack = useGoBack();
  const user = useAuthStore((s) => s.user);
  const { roleLabel } = useRoleOptions();

  const [detail, setDetail] = useState<ProjectDetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const [wbs, setWbs] = useState<WbsTask[]>([]);
  const [, setMilestones] = useState<Milestone[]>([]);
  const [milestoneTracking, setMilestoneTracking] = useState<MilestoneTrackingRow[]>([]);
  const [risks, setRisks] = useState<Risk[]>([]);
  const [costs, setCosts] = useState<CostEntry[]>([]);
  const [attachments, setAttachments] = useState<AttachmentItem[]>([]);
  const [members, setMembers] = useState<Member[]>([]);

  // ---------- 加载 ----------
  const loadDetail = useCallback(async () => {
    if (!id) return;
    try {
      setDetail(await api.get<ProjectDetailData>(`/projects/${id}`));
    } catch {
      // 已统一提示
    }
  }, [id]);

  const loadWbs = useCallback(async () => {
    if (!id) return;
    try {
      setWbs((await api.getList<WbsTask>(`/projects/${id}/wbs`)).items);
    } catch {
      // 已统一提示
    }
  }, [id]);

  const loadMilestones = useCallback(async () => {
    if (!id) return;
    try {
      setMilestones((await api.getList<Milestone>(`/projects/${id}/milestones`)).items);
    } catch {
      // 已统一提示
    }
  }, [id]);

  const loadMilestoneTracking = useCallback(async () => {
    if (!id) return;
    try {
      setMilestoneTracking((await api.getList<MilestoneTrackingRow>(`/projects/${id}/milestone-tracking`)).items);
    } catch {
      // 已统一提示
    }
  }, [id]);

  const loadRisks = useCallback(async () => {
    if (!id) return;
    try {
      setRisks((await api.getList<Risk>(`/projects/${id}/risks`)).items);
    } catch {
      // 已统一提示
    }
  }, [id]);

  const loadCosts = useCallback(async () => {
    if (!id) return;
    try {
      setCosts((await api.getList<CostEntry>(`/projects/${id}/costs`)).items);
    } catch {
      // 已统一提示
    }
  }, [id]);

  const loadAttachments = useCallback(async () => {
    if (!id) return;
    try {
      setAttachments(
        (await api.getList<AttachmentItem>('/attachments', { entity_type: 'project', entity_id: id })).items,
      );
    } catch {
      // 已统一提示
    }
  }, [id]);

  useEffect(() => {
    setLoading(true);
    void Promise.all([
      loadDetail(),
      loadWbs(),
      loadMilestones(),
      loadMilestoneTracking(),
      loadRisks(),
      loadCosts(),
      loadAttachments(),
    ]).finally(() => setLoading(false));
  }, [loadDetail, loadWbs, loadMilestones, loadMilestoneTracking, loadRisks, loadCosts, loadAttachments]);

  useEffect(() => {
    api
      .getList<Member>('/members', { page: 1, page_size: 2000, scope: 'it' })
      .then((res) => setMembers(res.items))
      .catch(() => undefined);
  }, []);

  const canEdit = detail?.can_edit ?? false;
  /** 示例数据只读：兜底隐藏 can_edit 覆盖不到的写入口（任务负责人路径/最新动态/附件上传） */
  const isExample = detail?.is_example === true;
  const isAdmin = !!user?.permissions?.['*'];
  const canDeleteExamples = isExample && isAdmin;
  const [completingStep, setCompletingStep] = useState<FlowDiagramStep | null>(null);
  const isFinal = detail?.status === 'closed' || detail?.status === 'cancelled';
  const currentProcessStep = detail?.process?.steps?.find((s) => s.seq === detail.process?.current_step_seq);
  const memberOptions = useMemo(
    () =>
      members.map((m) => ({
        value: m.id,
        label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
      })),
    [members],
  );

  // ---------- 状态流转 ----------
  // 重启弹窗（closed/completed → active）：可选流程回退节点
  const [restartTr, setRestartTr] = useState<AllowedTransition | null>(null);
  const [restartSeq, setRestartSeq] = useState<number | undefined>(undefined);
  const [restartSaving, setRestartSaving] = useState(false);

  // 暂停/关闭必填理由（M14.1）
  const [reasonTr, setReasonTr] = useState<AllowedTransition | null>(null);

  const runTransition = (tr: AllowedTransition) => {
    if (tr.to === 'active' && (detail?.status === 'closed' || detail?.status === 'completed')) {
      setRestartSeq(undefined);
      setRestartTr(tr);
      return;
    }
    if (tr.to === 'paused' || tr.to === 'closed') {
      setReasonTr(tr);
      return;
    }
    Modal.confirm({
      title: t('proj.confirmTransitionTitle', { name: tr.to_name }),
      content: t('proj.confirmTransitionContent', { name: tr.to_name }),
      onOk: async () => {
        await api.post(`/projects/${id}/transition`, { to: tr.to, fields: {} });
        message.success(t('proj.actionOk'));
        void loadDetail();
      },
    });
  };

  const submitRestart = async () => {
    if (!restartTr) return;
    setRestartSaving(true);
    try {
      await api.post(`/projects/${id}/transition`, {
        to: restartTr.to,
        // 选了节点才带 process_step_seq（流程实例回退到该步骤）；不带则流程不动
        fields: restartSeq != null ? { process_step_seq: restartSeq } : {},
      });
      message.success(t('proj.actionOk'));
      setRestartTr(null);
      void loadDetail();
    } catch {
      // 已统一提示
    } finally {
      setRestartSaving(false);
    }
  };

  // ---------- 编辑基本信息（共享 ProjectEditModal） ----------
  const [editOpen, setEditOpen] = useState(false);

  // ---------- 最新动态 ----------
  const saveLatestUpdate = async (text: string) => {
    if (!detail || text === (detail.latest_update ?? '')) return;
    try {
      await api.patch(`/projects/${id}`, { latest_update: text });
      message.success(t('proj.latestUpdated'));
      void loadDetail();
    } catch {
      // 已统一提示
    }
  };

  // ---------- WBS ----------
  const [taskModal, setTaskModal] = useState<{ mode: 'create' | 'edit'; task?: WbsTask; parent?: WbsTask } | null>(
    null,
  );
  const [taskSaving, setTaskSaving] = useState(false);
  const [taskForm] = Form.useForm();
  const [expandedKeys, setExpandedKeys] = useState<readonly React.Key[]>([]);

  const wbsTree = useMemo(() => buildWbsTree(wbs), [wbs]);
  const phaseTasks = useMemo(
    () => wbs
      .filter((task) => !task.parent_task_id)
      .slice()
      .sort((a, b) => a.wbs_code.localeCompare(b.wbs_code, undefined, { numeric: true })),
    [wbs],
  );
  useEffect(() => {
    setExpandedKeys(wbs.map((t) => t.id));
  }, [wbs]);

  const openTaskModal = (mode: 'create' | 'edit', task?: WbsTask, parent?: WbsTask) => {
    taskForm.resetFields();
    if (mode === 'edit' && task) {
      taskForm.setFieldsValue({
        name: task.name,
        assignee: task.assignee,
        dates: [dayjs(task.start_date), dayjs(task.end_date)],
        stage: task.stage ?? undefined,
        wbs_dict: task.wbs_dict ?? undefined,
        deliverable: task.deliverable ?? undefined,
        is_milestone: task.is_milestone ?? false,
        remarks: task.remarks ?? undefined,
        actuals: [
          task.actual_start ? dayjs(task.actual_start) : null,
          task.actual_end ? dayjs(task.actual_end) : null,
        ],
        description: task.description ?? undefined,
        predecessor_ids: task.predecessor_ids ?? [],
      });
    }
    setTaskModal({ mode, task, parent });
  };

  const submitTask = async () => {
    if (!taskModal) return;
    const v = await taskForm.validateFields();
    const base = {
      name: v.name,
      assignee: v.assignee,
      start_date: (v.dates[0] as Dayjs).format('YYYY-MM-DD'),
      end_date: (v.dates[1] as Dayjs).format('YYYY-MM-DD'),
      stage: v.stage || null,
      wbs_dict: v.wbs_dict || null,
      deliverable: v.deliverable || null,
      is_milestone: !!v.is_milestone,
      remarks: v.remarks || null,
      description: v.description || null,
      predecessor_ids: v.predecessor_ids ?? [],
    };
    setTaskSaving(true);
    try {
      if (taskModal.mode === 'edit' && taskModal.task) {
        const actuals = (v.actuals ?? []) as (Dayjs | null)[];
        await api.patch(`/wbs/${taskModal.task.id}`, {
          ...base,
          actual_start: actuals[0] ? actuals[0].format('YYYY-MM-DD') : null,
          actual_end: actuals[1] ? actuals[1].format('YYYY-MM-DD') : null,
        });
        message.success(t('proj.taskUpdated'));
      } else {
        await api.post(`/projects/${id}/wbs`, {
          ...base,
          parent_task_id: taskModal.parent?.id ?? null,
        });
        message.success(t('proj.taskCreated'));
      }
      setTaskModal(null);
      void loadWbs();
      void loadMilestoneTracking();
      void loadDetail();
    } catch {
      // 已统一提示
    } finally {
      setTaskSaving(false);
    }
  };

  const changeTaskProgress = async (task: WbsTask, progress: number) => {
    try {
      await api.patch(`/wbs/${task.id}`, { progress });
      message.success(t('proj.taskProgressUpdated'));
      void loadWbs();
      void loadMilestoneTracking();
      void loadDetail();
    } catch {
      // 403 等由拦截器统一中文提示
    }
  };

  const deleteTask = async (task: WbsTask) => {
    try {
      await api.delete(`/wbs/${task.id}`);
      message.success(t('proj.taskDeleted'));
      void loadWbs();
      void loadMilestoneTracking();
      void loadDetail();
    } catch {
      // 已统一提示（有子任务时后端返回 400）
    }
  };

  /** 完成度可编辑：有 projects.edit 或本人是任务负责人；示例数据一律只读 */
  const canChangeProgress = (task: WbsTask): boolean =>
    !isExample && (canEdit || (!!user?.person_id && user.person_id === task.assignee));

  // ---------- 成本 ----------
  const [costModalOpen, setCostModalOpen] = useState(false);
  const [costSaving, setCostSaving] = useState(false);
  const [costForm] = Form.useForm();

  const submitCost = async () => {
    const v = await costForm.validateFields();
    setCostSaving(true);
    try {
      await api.post(`/projects/${id}/costs`, {
        entry_date: (v.entry_date as Dayjs).format('YYYY-MM-DD'),
        amount_10k: v.amount_10k,
        note: v.note || null,
      });
      message.success(t('proj.costAdded'));
      setCostModalOpen(false);
      void loadCosts();
      void loadDetail();
    } catch {
      // 已统一提示
    } finally {
      setCostSaving(false);
    }
  };

  const deleteCost = async (c: CostEntry) => {
    try {
      await api.delete(`/costs/${c.id}`);
      message.success(t('proj.costDeleted'));
      void loadCosts();
      void loadDetail();
    } catch {
      // 已统一提示
    }
  };

  // ---------- 风险 ----------
  const [riskModal, setRiskModal] = useState<{ mode: 'create' | 'edit'; risk?: Risk } | null>(null);
  const [riskSaving, setRiskSaving] = useState(false);
  const [riskForm] = Form.useForm();

  const openRiskModal = (mode: 'create' | 'edit', risk?: Risk) => {
    riskForm.resetFields();
    if (mode === 'edit' && risk) {
      riskForm.setFieldsValue({
        title: risk.title,
        probability: risk.probability,
        impact: risk.impact,
        mitigation: risk.mitigation ?? undefined,
        status: risk.status,
      });
    }
    setRiskModal({ mode, risk });
  };

  const submitRisk = async () => {
    if (!riskModal) return;
    const v = await riskForm.validateFields();
    setRiskSaving(true);
    try {
      if (riskModal.mode === 'edit' && riskModal.risk) {
        await api.patch(`/risks/${riskModal.risk.id}`, {
          title: v.title,
          probability: v.probability,
          impact: v.impact,
          mitigation: v.mitigation || null,
          status: v.status,
        });
        message.success(t('proj.riskUpdated'));
      } else {
        await api.post(`/projects/${id}/risks`, {
          title: v.title,
          probability: v.probability,
          impact: v.impact,
          mitigation: v.mitigation || null,
        });
        message.success(t('proj.riskAdded'));
      }
      setRiskModal(null);
      void loadRisks();
      void loadDetail();
    } catch {
      // 已统一提示
    } finally {
      setRiskSaving(false);
    }
  };

  // ---------- 渲染 ----------
  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" />
      </div>
    );
  }
  if (!detail) {
    return (
      <Card>
        <Typography.Text type="secondary">{t('proj.notFound')}</Typography.Text>
      </Card>
    );
  }

  // ----- 概述：章程信息分段 -----
  const orgMemberColumns: ColumnsType<ProjectOrgEntry> = [
    { title: t('proj.charter.col.name'), dataIndex: 'name', width: 140 },
    { title: t('proj.charter.col.role'), dataIndex: 'role', width: 180, render: (v) => v || '-' },
    { title: t('proj.charter.col.duty'), dataIndex: 'duty', render: (v) => v || '-' },
  ];
  const stakeholderColumns: ColumnsType<ProjectOrgEntry> = [
    { title: t('proj.charter.col.name'), dataIndex: 'name', width: 140 },
    { title: t('proj.charter.col.sRole'), dataIndex: 'role', width: 180, render: (v) => v || '-' },
    { title: t('proj.charter.col.concern'), dataIndex: 'duty', render: (v) => v || '-' },
  ];
  const renderOrgTable = (rows: ProjectOrgEntry[], columns: ColumnsType<ProjectOrgEntry>) =>
    rows.length === 0 ? (
      <Typography.Text type="secondary">-</Typography.Text>
    ) : (
      <Table<ProjectOrgEntry>
        size="small"
        rowKey={(_, i) => i ?? 0}
        columns={columns}
        dataSource={rows}
        pagination={false}
      />
    );

  const charterCard = (
    <Card title={t('proj.charter.section')} size="small">
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <CharterSection title={t('proj.charter.background')}>
          <CharterText value={detail.background} />
        </CharterSection>
        <CharterSection title={t('proj.charter.goals')}>
          <CharterText value={detail.goals} />
        </CharterSection>
        <CharterSection title={t('proj.charter.scope')}>
          <Row gutter={[16, 12]}>
            <Col xs={24} md={12}>
              <Typography.Text type="secondary">
                <span style={{ color: '#52c41a', marginRight: 4 }}>✔</span>
                {t('proj.charter.scopeIn')}
              </Typography.Text>
              <div style={{ marginTop: 4 }}>
                <CharterText value={detail.scope_in} />
              </div>
            </Col>
            <Col xs={24} md={12}>
              <Typography.Text type="secondary">
                <span style={{ color: '#ff4d4f', marginRight: 4 }}>✘</span>
                {t('proj.charter.scopeOut')}
              </Typography.Text>
              <div style={{ marginTop: 4 }}>
                <CharterText value={detail.scope_out} />
              </div>
            </Col>
          </Row>
        </CharterSection>
        <CharterSection title={t('proj.charter.budgetRes')}>
          <Space direction="vertical" size={4} style={{ width: '100%' }}>
            <span>
              <Typography.Text type="secondary" style={{ marginRight: 8 }}>
                {t('proj.d.budget')}
              </Typography.Text>
              {fmt10k(detail.budget_10k)}
            </span>
            <CharterText value={detail.resource_note} />
          </Space>
        </CharterSection>
        <CharterSection title={t('proj.charter.org')}>
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <span>
              <Typography.Text type="secondary" style={{ marginRight: 8 }}>
                {t('proj.pm')}
              </Typography.Text>
              {detail.pm_name ? <Tag color="blue">{detail.pm_name}</Tag> : '-'}
            </span>
            <div>
              <Typography.Text type="secondary">{t('proj.charter.members')}</Typography.Text>
              <div style={{ marginTop: 4 }}>{renderOrgTable(detail.org_members ?? [], orgMemberColumns)}</div>
            </div>
            <div>
              <Typography.Text type="secondary">{t('proj.charter.stakeholders')}</Typography.Text>
              <div style={{ marginTop: 4 }}>{renderOrgTable(detail.stakeholders ?? [], stakeholderColumns)}</div>
            </div>
          </Space>
        </CharterSection>
        {detail.description && (
          <CharterSection title={t('proj.charter.other')}>
            <CharterText value={detail.description} />
          </CharterSection>
        )}
      </Space>
    </Card>
  );

  // ----- 概述 -----
  const overviewTab = (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Descriptions column={2} size="small" bordered>
        <Descriptions.Item label={t('proj.pm')}>{detail.pm_name ?? '-'}</Descriptions.Item>
        <Descriptions.Item label={t('proj.belongPortfolio')}>{detail.portfolio_name ?? '-'}</Descriptions.Item>
        <Descriptions.Item label={t('proj.planned')} contentStyle={{ whiteSpace: 'nowrap' }}>
          {detail.planned_start} ~ {detail.planned_end}
        </Descriptions.Item>
        <Descriptions.Item label={t('proj.d.actual')} contentStyle={{ whiteSpace: 'nowrap' }}>
          {detail.actual_start ?? '-'} ~ {detail.actual_end ?? '-'}
        </Descriptions.Item>
        <Descriptions.Item label={t('proj.d.budget')}>{fmt10k(detail.budget_10k)}</Descriptions.Item>
        <Descriptions.Item label={t('proj.d.actualCost')}>{fmt10k(detail.actual_cost_10k)}</Descriptions.Item>
        <Descriptions.Item label={t('proj.d.budgetUsageRate')}>
          <span style={detail.budget_usage != null && detail.budget_usage > 100 ? { color: '#ff4d4f' } : undefined}>
            {fmtPct(detail.budget_usage)}
          </span>
        </Descriptions.Item>
        <Descriptions.Item label="SPI / CPI">
          {detail.spi ?? '-'} / {detail.cpi ?? '-'}
        </Descriptions.Item>
        <Descriptions.Item label={t('proj.d.deviation')}>
          {detail.deviation == null ? (
            '-'
          ) : (
            <span style={detail.deviation > 15 ? { color: '#ff4d4f' } : undefined}>
              {t('proj.pctPoints', { n: detail.deviation })}
            </span>
          )}
        </Descriptions.Item>
        <Descriptions.Item label={t('proj.d.taskMsRisk')}>
          {t('proj.ov.tasks', { done: detail.task_done, total: detail.task_total })} ·{' '}
          {t('proj.ov.milestones', { n: detail.milestone_total })}
          {detail.milestone_overdue > 0 && (
            <span style={{ color: '#ff4d4f' }}>{t('proj.ov.overdueParen', { n: detail.milestone_overdue })}</span>
          )}
          {' '}· {t('proj.ov.openRisks', { n: detail.open_risks })}
          {detail.red_risks > 0 && (
            <span style={{ color: '#ff4d4f' }}>{t('proj.ov.redParen', { n: detail.red_risks })}</span>
          )}
        </Descriptions.Item>
      </Descriptions>

      {charterCard}

      <Card title={t('proj.latestUpdate')} size="small">
        <Typography.Paragraph
          style={{ marginBottom: 0 }}
          editable={
            canEdit && !isExample
              ? {
                  text: detail.latest_update ?? '',
                  maxLength: 200,
                  tooltip: t('proj.editLatestTooltip'),
                  onChange: (v) => void saveLatestUpdate(v),
                }
              : false
          }
        >
          {detail.latest_update || t('proj.noUpdate')}
        </Typography.Paragraph>
      </Card>

      <Card title={t('proj.linkedReq')} size="small">
        {(detail.linked_requirements ?? []).length === 0 ? (
          <Typography.Text type="secondary">{t('proj.noLinkedReq')}</Typography.Text>
        ) : (
          <Space direction="vertical" size={4} style={{ width: '100%' }}>
            {(detail.linked_requirements ?? []).map((r) => (
              <div key={r.id}>
                <Space size={8}>
                  <Link to={`/requirements/${r.id}`}>{r.requirement_code}</Link>
                  <span>{r.title}</span>
                  {r.moscow && <Tag>{et.moscow(r.moscow)}</Tag>}
                  <Tag>{r.status_name}</Tag>
                </Space>
                {r.relation_reason && (
                  <Typography.Text type="secondary" style={{ display: 'block', marginTop: 2 }}>
                    {r.relation_reason}
                  </Typography.Text>
                )}
              </div>
            ))}
          </Space>
        )}
      </Card>

      <RecordRelationsPanel
        entityType="project"
        entityId={detail.id}
        excludeRelationTypes={['converted_to_project']}
        hideWhenEmpty
      />

      <Card title={t('proj.progress')} size="small">
        {detail.progress == null ? (
          <Typography.Text type="secondary">{t('proj.noWbsProgress')}</Typography.Text>
        ) : (
          <>
            <Progress percent={detail.progress} format={(p) => `${p ?? 0}%`} />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {t('proj.plannedProgress', { pct: fmtPct(detail.planned_progress) })}
              {detail.deviation != null && ` · ${t('proj.deviationSuffix', { n: detail.deviation })}`}
              {detail.spi != null && ` · ${t('proj.spiSuffix', { v: detail.spi })}`}
            </Typography.Text>
          </>
        )}
      </Card>
    </Space>
  );

  // ----- 进度 -----
  // 里程碑跟踪（派生只读，来自 WBS is_milestone=true）
  const mtColumns: ColumnsType<MilestoneTrackingRow> = [
    { title: t('proj.mt.col.code'), dataIndex: 'wbs_code', width: 100 },
    { title: t('proj.mt.col.name'), dataIndex: 'name', ellipsis: true },
    { title: t('proj.mt.col.stage'), dataIndex: 'stage', width: 120, render: (v) => v || '-' },
    { title: t('proj.mt.col.assignee'), dataIndex: 'assignee_name', width: 110, render: (v) => v || '-' },
    { title: t('proj.mt.col.plannedEnd'), dataIndex: 'end_date', width: 120, onCell: () => ({ className: 'cell-nowrap' }) },
    { title: t('proj.mt.col.actualEnd'), dataIndex: 'actual_end', width: 120, onCell: () => ({ className: 'cell-nowrap' }), render: (v) => v || '-' },
    {
      title: t('proj.mt.col.deviation'),
      dataIndex: 'schedule_deviation',
      width: 110,
      align: 'center',
      render: (v: number | null) => renderDeviation(v),
    },
    {
      title: t('common.status'),
      dataIndex: 'status',
      width: 100,
      render: (v: WbsStatus) => <WbsStatusTag status={v} label={et.wbsStatus(v)} />,
    },
  ];

  const wbsColumns: ColumnsType<WbsNode> = [
    { title: t('proj.wbs.col.stage'), dataIndex: 'stage', width: 110, render: (v) => v || '-' },
    { title: t('proj.wbs.col.code'), dataIndex: 'wbs_code', width: 90 },
    { title: t('proj.wbs.col.name'), dataIndex: 'name', width: 200, ellipsis: true },
    {
      title: t('proj.wbs.col.wbsDict'),
      dataIndex: 'wbs_dict',
      width: 160,
      ellipsis: true,
      render: (v: string | null) => (v ? <Tooltip title={v}>{v}</Tooltip> : '-'),
    },
    {
      title: t('proj.wbs.col.deliverable'),
      dataIndex: 'deliverable',
      width: 160,
      ellipsis: true,
      render: (v: string | null) => (v ? <Tooltip title={v}>{v}</Tooltip> : '-'),
    },
    { title: t('proj.wbs.col.assignee'), dataIndex: 'assignee_name', width: 100, render: (v) => v || '-' },
    {
      title: t('proj.wbs.col.milestone'),
      dataIndex: 'is_milestone',
      width: 90,
      align: 'center',
      render: (v: boolean) =>
        v ? (
          <Tag color="blue" style={{ fontWeight: 700 }}>
            {t('proj.yes')}
          </Tag>
        ) : (
          <Typography.Text type="secondary">{t('proj.no')}</Typography.Text>
        ),
    },
    {
      title: t('proj.wbs.col.predecessors'),
      dataIndex: 'predecessor_codes',
      width: 130,
      ellipsis: true,
      render: (v: string[] | null) => (v?.length ? v.join('、') : '-'),
    },
    { title: t('proj.wbs.col.plannedStart'), dataIndex: 'start_date', width: 120, onCell: () => ({ className: 'cell-nowrap' }) },
    { title: t('proj.wbs.col.plannedEnd'), dataIndex: 'end_date', width: 120, onCell: () => ({ className: 'cell-nowrap' }) },
    { title: t('proj.wbs.col.actualStart'), dataIndex: 'actual_start', width: 120, onCell: () => ({ className: 'cell-nowrap' }), render: (v) => v || '-' },
    { title: t('proj.wbs.col.actualEnd'), dataIndex: 'actual_end', width: 120, onCell: () => ({ className: 'cell-nowrap' }), render: (v) => v || '-' },
    {
      title: t('proj.wbs.col.deviation'),
      dataIndex: 'schedule_deviation',
      width: 120,
      align: 'center',
      render: (v: number | null) => renderDeviation(v),
    },
    {
      title: t('proj.wbs.col.progress'),
      dataIndex: 'progress',
      width: 110,
      render: (v: number, r) =>
        canChangeProgress(r) ? (
          <WbsProgressEditor
            value={v}
            customLabel={t('proj.wbs.progressCustom')}
            aggregateLabel={t('proj.wbs.progressAggregate')}
            cascadeLabel={t('proj.wbs.progressCascade')}
            hasChildren={Boolean(r.children?.length)}
            onChange={(p) => void changeTaskProgress(r, p)}
          />
        ) : (
          `${v}%`
        ),
    },
    {
      title: t('common.status'),
      dataIndex: 'status',
      width: 100,
      render: (v: WbsStatus) => <WbsStatusTag status={v} label={et.wbsStatus(v)} />,
    },
    {
      title: t('proj.wbs.col.remarks'),
      dataIndex: 'remarks',
      width: 150,
      ellipsis: true,
      render: (v: string | null) => (v ? <Tooltip title={v}>{v}</Tooltip> : '-'),
    },
    ...(canEdit || canDeleteExamples
      ? [
          {
            title: t('common.actions'),
            key: 'action',
            width: 190,
            fixed: 'right' as const,
            render: (_: unknown, r: WbsNode) => (
              <Space size={0}>
                {!isExample && canEdit && (
                  <>
                    <Button type="link" size="small" onClick={() => openTaskModal('edit', r)}>
                      {t('common.edit')}
                    </Button>
                    <Button type="link" size="small" onClick={() => openTaskModal('create', undefined, r)}>
                      {t('proj.addSubtask')}
                    </Button>
                  </>
                )}
                {(!isExample && canEdit) || canDeleteExamples ? (
                  <Popconfirm title={t('proj.confirmDeleteTask')} onConfirm={() => void deleteTask(r)}>
                    <Button type="link" size="small" danger>
                      {t('common.delete')}
                    </Button>
                  </Popconfirm>
                ) : null}
              </Space>
            ),
          } as ColumnsType<WbsNode>[number],
        ]
      : []),
  ];

  const progressTab = (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {canEdit && (
        <Card size="small">
          <Space wrap>
            <ImportButtons
              templateUrl="/project-progress/template"
              importUrl={`/projects/${id}/import-progress`}
              onDone={() => {
                void loadWbs();
                void loadMilestones();
                void loadMilestoneTracking();
                void loadDetail();
              }}
              buttonText={t('proj.importWbsMs')}
            />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {t('proj.importHint')}
            </Typography.Text>
          </Space>
        </Card>
      )}
      <Card title={t('proj.phaseProgress')} size="small">
          {phaseTasks.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('proj.phaseEmpty')} />
          ) : (
            <div style={{ overflowX: 'auto', padding: '12px 4px 4px' }}>
              <div style={{ position: 'relative', minWidth: Math.max(phaseTasks.length * 180, 640), padding: '0 24px' }}>
                <div style={{ position: 'absolute', left: 42, right: 42, top: 16, height: 2, background: '#d9d9d9' }} />
                <Space size={0} style={{ position: 'relative', width: '100%', justifyContent: 'space-between' }}>
                  {phaseTasks.map((phase) => (
                    <div key={phase.id} style={{ width: 160, textAlign: 'center' }}>
                      <div style={{ width: 14, height: 14, margin: '0 auto 8px', borderRadius: '50%', background: WBS_TAG_COLORS[phase.status] === 'success' ? '#52c41a' : '#1677ff', border: '2px solid #fff', boxShadow: '0 0 0 1px #91caff' }} />
                      <Typography.Text strong ellipsis={{ tooltip: phase.name }}>{phase.name}</Typography.Text>
                      <div style={{ marginTop: 6 }}>
                        <Progress percent={phase.progress} size="small" status={phase.status === '已延期' ? 'exception' : undefined} />
                      </div>
                      <WbsStatusTag status={phase.status} label={et.wbsStatus(phase.status)} />
                    </div>
                  ))}
                </Space>
              </div>
            </div>
          )}
      </Card>
      <Card title={t('proj.gantt')} size="small">
        <GanttChart
          tasks={wbs}
          rangeStart={detail.planned_start}
          rangeEnd={detail.planned_end}
        />
      </Card>

      <Card title={t('proj.mtTitle')} size="small">
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Alert type="info" showIcon message={t('proj.mtAlert')} />
          <StickyTable<MilestoneTrackingRow>
            size="small"
            rowKey="id"
            columns={mtColumns}
            dataSource={milestoneTracking}
            pagination={false}
            sticky
            scroll={{ x: 'max-content' }}
            locale={{ emptyText: t('proj.emptyMt') }}
          />
        </Space>
      </Card>

      <Card
        title={t('proj.wbsTasks')}
        size="small"
        extra={
          canEdit && (
            <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => openTaskModal('create')}>
              {t('proj.newTask')}
            </Button>
          )
        }
      >
        <StickyTable<WbsNode>
          size="small"
          rowKey="id"
          columns={wbsColumns}
          dataSource={wbsTree}
          pagination={false}
          sticky
          scroll={{ x: 'max-content' }}
          freezeColumns={3}
          resizable
          rowResizable
          storageKey={`project-wbs-layout:${id}`}
          expandable={{
            expandedRowKeys: expandedKeys,
            onExpandedRowsChange: setExpandedKeys,
          }}
          locale={{ emptyText: t('proj.emptyWbs') }}
        />
      </Card>
    </Space>
  );

  // ----- 成本 -----
  const costColumns: ColumnsType<CostEntry> = [
    { title: t('proj.cost.col.date'), dataIndex: 'entry_date', width: 130, onCell: () => ({ className: 'cell-nowrap' }) },
    { title: t('proj.cost.col.amountWan'), dataIndex: 'amount_10k', width: 130 },
    { title: t('proj.cost.col.note'), dataIndex: 'note', ellipsis: true, render: (v) => v || '-' },
    ...(canEdit || canDeleteExamples
      ? [
          {
            title: t('common.actions'),
            key: 'action',
            width: 80,
            render: (_: unknown, r: CostEntry) =>
              (!isExample && canEdit) || canDeleteExamples ? (
                <Popconfirm title={t('proj.confirmDeleteCost')} onConfirm={() => void deleteCost(r)}>
                  <Button type="link" size="small" danger>
                    {t('common.delete')}
                  </Button>
                </Popconfirm>
              ) : null,
          } as ColumnsType<CostEntry>[number],
        ]
      : []),
  ];

  const costTab = (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Row gutter={16}>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title={t('proj.budgetWan')} value={detail.budget_10k ?? '-'} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title={t('proj.stat.actualCostWan')} value={detail.actual_cost_10k} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic
              title={t('proj.d.budgetUsageRate')}
              value={detail.budget_usage ?? '-'}
              suffix={detail.budget_usage != null ? '%' : undefined}
              valueStyle={detail.budget_usage != null && detail.budget_usage > 100 ? { color: '#ff4d4f' } : undefined}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic
              title="CPI"
              value={detail.cpi ?? '-'}
              valueStyle={detail.cpi != null && detail.cpi < 1 ? { color: '#ff4d4f' } : undefined}
            />
          </Card>
        </Col>
      </Row>

      <Card
        title={t('proj.costDetail')}
        size="small"
        extra={
          canEdit && (
            <Button
              size="small"
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => {
                costForm.resetFields();
                setCostModalOpen(true);
              }}
            >
              {t('proj.addEntry')}
            </Button>
          )
        }
      >
        <Table<CostEntry>
          size="small"
          rowKey="id"
          columns={costColumns}
          dataSource={costs}
          pagination={false}
          locale={{ emptyText: t('proj.emptyCost') }}
        />
      </Card>
    </Space>
  );

  // ----- 风险 -----
  const openRisks = risks.filter((r) => r.status === '开放');
  const matrixCellColor = (p: RiskGrade, i: RiskGrade): string => {
    if (p === '高' && i === '高') return '#ff7875';
    if (p === '高' || i === '高') return '#ffd666';
    return '#b7eb8f';
  };

  const riskColumns: ColumnsType<Risk> = [
    { title: t('proj.risk.col.title'), dataIndex: 'title', ellipsis: true },
    { title: t('proj.risk.col.prob'), dataIndex: 'probability', width: 70, render: (v) => et.riskGrade(v) },
    { title: t('proj.risk.col.impact'), dataIndex: 'impact', width: 70, render: (v) => et.riskGrade(v) },
    {
      title: t('proj.risk.col.level'),
      key: 'level',
      width: 80,
      render: (_, r) => <RiskLevelTag probability={r.probability} impact={r.impact} />,
    },
    { title: t('proj.risk.col.mitigation'), dataIndex: 'mitigation', ellipsis: true, render: (v) => v || '-' },
    {
      title: t('common.status'),
      dataIndex: 'status',
      width: 90,
      render: (v: Risk['status']) => <Tag color={v === '开放' ? 'orange' : 'default'}>{et.riskStatus(v)}</Tag>,
    },
    ...(canEdit
      ? [
          {
            title: t('common.actions'),
            key: 'action',
            width: 70,
            render: (_: unknown, r: Risk) => (
              <Button type="link" size="small" onClick={() => openRiskModal('edit', r)}>
                {t('common.edit')}
              </Button>
            ),
          } as ColumnsType<Risk>[number],
        ]
      : []),
  ];

  const riskTab = (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card title={t('proj.riskMatrixTitle')} size="small">
        <div style={{ display: 'grid', gridTemplateColumns: '90px repeat(3, 90px)', gap: 4, fontSize: 13 }}>
          <div />
          {RISK_GRADES.map((i) => (
            <div key={`h-${i}`} style={{ textAlign: 'center', color: 'rgba(0,0,0,0.45)' }}>
              {t('proj.impactAxis', { g: et.riskGrade(i) })}
            </div>
          ))}
          {RISK_GRADES.map((p) => (
            <div key={`row-${p}`} style={{ display: 'contents' }}>
              <div style={{ lineHeight: '44px', color: 'rgba(0,0,0,0.45)' }}>{t('proj.probAxis', { g: et.riskGrade(p) })}</div>
              {RISK_GRADES.map((i) => {
                const count = openRisks.filter((r) => r.probability === p && r.impact === i).length;
                return (
                  <div
                    key={`${p}-${i}`}
                    style={{
                      height: 44,
                      lineHeight: '44px',
                      textAlign: 'center',
                      borderRadius: 6,
                      background: matrixCellColor(p, i),
                      color: 'rgba(0,0,0,0.75)',
                      fontWeight: count > 0 ? 700 : 400,
                      opacity: count > 0 ? 1 : 0.45,
                    }}
                  >
                    {count}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </Card>

      <Card
        title={t('proj.riskList')}
        size="small"
        extra={
          canEdit && (
            <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => openRiskModal('create')}>
              {t('proj.newRisk')}
            </Button>
          )
        }
      >
        <Table<Risk>
          size="small"
          rowKey="id"
          columns={riskColumns}
          dataSource={risks}
          pagination={false}
          locale={{ emptyText: t('proj.emptyRisk') }}
        />
      </Card>
    </Space>
  );

  // ----- 文档 -----
  const attachmentColumns: ColumnsType<AttachmentItem> = [
    {
      title: t('proj.att.col.filename'),
      dataIndex: 'filename',
      ellipsis: true,
      render: (v: string, r) => (
        <Button
          type="link"
          size="small"
          style={{ padding: 0 }}
          icon={<DownloadOutlined />}
          onClick={() => void api.download(`/attachments/${r.id}/download`)}
        >
          {v}
        </Button>
      ),
    },
    { title: t('proj.att.col.size'), dataIndex: 'size', width: 100, render: (v: number) => formatSize(v) },
    {
      title: t('proj.att.col.uploadedAt'),
      dataIndex: 'created_at',
      width: 160,
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'),
    },
  ];

  const docsTab = (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Alert
        type="info"
        showIcon
        message={t('proj.charterImport')}
        description={
          <span>
            {t('proj.charterAlert.pre')}
            <Link to="/projects">{t('proj.charterAlert.link')}</Link>
            {t('proj.charterAlert.post')}
          </span>
        }
      />
      <Card
        title={t('proj.attachments')}
        size="small"
        extra={
          !isExample && (
            <Upload
              showUploadList={false}
              customRequest={({ file, onSuccess, onError }) => {
                api
                  .upload<AttachmentItem>(`/attachments?entity_type=project&entity_id=${id}`, file as File)
                  .then((r) => {
                    onSuccess?.(r);
                    message.success(t('proj.attUploaded'));
                    void loadAttachments();
                  })
                  .catch((e) => onError?.(e as Error));
              }}
            >
              <Button size="small" type="primary" icon={<UploadOutlined />}>
                {t('proj.upload')}
              </Button>
            </Upload>
          )
        }
      >
        <Table<AttachmentItem>
          size="small"
          rowKey="id"
          columns={attachmentColumns}
          dataSource={attachments}
          pagination={false}
          locale={{ emptyText: t('proj.emptyAtt') }}
        />
      </Card>
    </Space>
  );

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {isExample && <ExampleAlert />}
      <DocumentTypeHint documentType="project" />
      {/* 头部 */}
      <Card>
        <Space style={{ width: '100%', justifyContent: 'space-between', flexWrap: 'wrap' }}>
          <Space size="middle" wrap>
            <Button icon={<ArrowLeftOutlined />} onClick={() => goBack('/projects/list')}>
              {t('proj.back')}
            </Button>
            <Typography.Title level={4} style={{ margin: 0 }}>
              {detail.project_code} · {detail.name}
            </Typography.Title>
            <StatusBadge status={detail.status} name={detail.status_name} />
            <HealthDot health={detail.health} />
          </Space>
          {canEdit && (
            <Space wrap>
              {!isFinal && (
                <Button icon={<EditOutlined />} onClick={() => setEditOpen(true)}>
                  {t('common.edit')}
                </Button>
              )}
              {(detail.allowed_transitions ?? []).map((tr) => (
                <Button
                  key={tr.to}
                  type={tr.to === 'cancelled' ? 'default' : 'primary'}
                  danger={tr.to === 'cancelled'}
                  onClick={() => runTransition(tr)}
                >
                  {tr.to_name}
                </Button>
              ))}
            </Space>
          )}
          <ProcessActionButtons
            step={currentProcessStep}
            disabled={isExample}
            onDone={() => void loadDetail()}
          />
        </Space>
      </Card>

      {/* 流程示意 */}
      {detail.process && detail.process.steps?.length > 0 && (
        <Card title={t('proj.flowTitle', { name: detail.process.definition_name })} size="small">
          <FlowDiagram
            steps={detail.process.steps}
            roleLabel={roleLabel}
            currentSeq={detail.process.current_step_seq}
            // M18：能否完成由 FlowDiagram 按任务处理人判定（与后端 _require_task_operator 一致）
            onCompleteStep={!isExample ? setCompletingStep : undefined}
          />
        </Card>
      )}
      <CompleteStepModal
        step={completingStep}
        onClose={() => setCompletingStep(null)}
        onDone={() => void loadDetail()}
      />
      <ReasonModal
        open={!!reasonTr}
        opLabel={reasonTr?.to_name ?? ''}
        projectName={detail.name}
        onClose={() => setReasonTr(null)}
        onSubmit={async (reason) => {
          if (!reasonTr) return;
          await api.post(`/projects/${id}/transition`, { to: reasonTr.to, fields: { reason } });
          message.success(t('proj.actionOk'));
          setReasonTr(null);
          void loadDetail();
        }}
      />

      <Card>
        <Tabs
          items={[
            { key: 'overview', label: t('proj.tab.overview'), children: overviewTab },
            { key: 'progress', label: t('proj.tab.progress'), children: progressTab },
            { key: 'cost', label: t('proj.tab.cost'), children: costTab },
            { key: 'risk', label: t('proj.tab.risk'), children: riskTab },
            { key: 'docs', label: t('proj.tab.docs'), children: docsTab },
          ]}
        />
      </Card>

      {/* 编辑基本信息（共享编辑弹窗，含实际起止） */}
      <ProjectEditModal
        project={
          editOpen
            ? {
                id: detail.id,
                name: detail.name,
                pm: detail.pm,
                planned_start: detail.planned_start,
                planned_end: detail.planned_end,
                portfolio_id: detail.portfolio_id,
                service_item_id: detail.service_item_id,
                budget_10k: detail.budget_10k,
                description: detail.description,
                actual_start: detail.actual_start,
                actual_end: detail.actual_end,
                background: detail.background,
                goals: detail.goals,
                scope_in: detail.scope_in,
                scope_out: detail.scope_out,
                resource_note: detail.resource_note,
                org_members: detail.org_members ?? [],
                stakeholders: detail.stakeholders ?? [],
              }
            : null
        }
        onClose={() => setEditOpen(false)}
        onSaved={() => {
          setEditOpen(false);
          void loadDetail();
        }}
      />

      {/* 重启项目 Modal（closed/completed → active，可选流程回退节点） */}
      <Modal
        title={t('proj.restartTitle')}
        open={!!restartTr}
        onOk={() => void submitRestart()}
        confirmLoading={restartSaving}
        onCancel={() => setRestartTr(null)}
        destroyOnClose
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Typography.Text type="secondary">{t('proj.restartHint')}</Typography.Text>
          {(detail.process?.steps?.length ?? 0) > 0 && (
            <div>
              <div style={{ marginBottom: 4 }}>{t('proj.restartRewindLabel')}</div>
              <Select
                allowClear
                style={{ width: '100%' }}
                placeholder={t('proj.restartRewindPlaceholder')}
                value={restartSeq}
                onChange={(v?: number) => setRestartSeq(v)}
                options={(detail.process?.steps ?? []).map((s) => ({
                  value: s.seq,
                  label: `${s.seq}. ${s.name}`,
                }))}
              />
            </div>
          )}
        </Space>
      </Modal>

      {/* 新建/编辑任务 Modal */}
      <Modal
        title={
          taskModal?.mode === 'edit'
            ? t('proj.editTaskTitle', { name: taskModal.task?.name ?? '' })
            : taskModal?.parent
              ? t('proj.newSubtaskTitle', { name: taskModal.parent.name })
              : t('proj.newTask')
        }
        open={!!taskModal}
        width={600}
        onOk={() => void submitTask()}
        confirmLoading={taskSaving}
        onCancel={() => setTaskModal(null)}
        destroyOnClose
      >
        <Form form={taskForm} layout="vertical" preserve={false} initialValues={{ is_milestone: false }}>
          <Form.Item name="name" label={t('proj.taskName')} rules={[{ required: true, message: t('proj.taskNameRequired') }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="stage" label={t('proj.stage')}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="assignee" label={t('proj.assignee')} rules={[{ required: true, message: t('proj.assigneeRequired') }]}>
            <Select showSearch optionFilterProp="label" options={memberOptions} />
          </Form.Item>
          <Form.Item name="dates" label={t('proj.dateRange')} rules={[{ required: true, message: t('proj.dateRangeRequired') }]}>
            <DatePicker.RangePicker style={{ width: '100%' }} />
          </Form.Item>
          {taskModal?.mode === 'edit' && (
            <Form.Item name="actuals" label={`${t('proj.actualStart')} ~ ${t('proj.actualEnd')}`}>
              <DatePicker.RangePicker style={{ width: '100%' }} allowEmpty={[true, true]} />
            </Form.Item>
          )}
          <Form.Item name="wbs_dict" label={t('proj.wbsDict')}>
            <Input.TextArea rows={2} maxLength={1000} placeholder={t('proj.wbsDictPlaceholder')} />
          </Form.Item>
          <Form.Item name="deliverable" label={t('proj.deliverable')}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="is_milestone" label={t('proj.isMilestone')} valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item
            name="predecessor_ids"
            label={t('proj.predecessor')}
            extra={t('proj.predecessorExtra')}
          >
            <Select
              mode="multiple"
              allowClear
              optionFilterProp="label"
              options={wbs
                .filter((t) => t.id !== taskModal?.task?.id)
                .map((t) => ({ value: t.id, label: `${t.wbs_code} ${t.name}` }))}
            />
          </Form.Item>
          <Form.Item name="remarks" label={t('proj.remarks')}>
            <Input.TextArea rows={2} maxLength={1000} />
          </Form.Item>
          <Form.Item name="description" label={t('proj.taskDesc')}>
            <Input.TextArea rows={2} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 新增成本明细 Modal */}
      <Modal
        title={t('proj.addCostTitle')}
        open={costModalOpen}
        onOk={() => void submitCost()}
        confirmLoading={costSaving}
        onCancel={() => setCostModalOpen(false)}
        destroyOnClose
      >
        <Form form={costForm} layout="vertical" preserve={false}>
          <Form.Item name="entry_date" label={t('proj.cost.col.date')} rules={[{ required: true, message: t('proj.cost.dateRequired') }]}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="amount_10k"
            label={t('proj.cost.col.amountWan')}
            rules={[{ required: true, message: t('proj.cost.amountRequired') }]}
          >
            <InputNumber min={0.0001} precision={4} style={{ width: '100%' }} placeholder={t('proj.cost.amountPlaceholder')} />
          </Form.Item>
          <Form.Item name="note" label={t('proj.cost.col.note')}>
            <Input maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 新建/编辑风险 Modal */}
      <Modal
        title={riskModal?.mode === 'edit' ? t('proj.editRisk') : t('proj.newRisk')}
        open={!!riskModal}
        onOk={() => void submitRisk()}
        confirmLoading={riskSaving}
        onCancel={() => setRiskModal(null)}
        destroyOnClose
      >
        <Form
          form={riskForm}
          layout="vertical"
          preserve={false}
          initialValues={{ probability: '中', impact: '中', status: '开放' }}
        >
          <Form.Item name="title" label={t('proj.riskTitle')} rules={[{ required: true, message: t('proj.riskTitleRequired') }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Space size={16}>
            <Form.Item name="probability" label={t('proj.riskProb')} rules={[{ required: true }]} style={{ width: 120 }}>
              <Select options={RISK_GRADES.map((g) => ({ value: g, label: et.riskGrade(g) }))} />
            </Form.Item>
            <Form.Item name="impact" label={t('proj.riskImpact')} rules={[{ required: true }]} style={{ width: 120 }}>
              <Select options={RISK_GRADES.map((g) => ({ value: g, label: et.riskGrade(g) }))} />
            </Form.Item>
            {riskModal?.mode === 'edit' && (
              <Form.Item name="status" label={t('common.status')} style={{ width: 120 }}>
                <Select options={['开放', '已关闭'].map((s) => ({ value: s, label: et.riskStatus(s) }))} />
              </Form.Item>
            )}
          </Space>
          <Form.Item name="mitigation" label={t('proj.mitigation')}>
            <Input.TextArea rows={3} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );
}
