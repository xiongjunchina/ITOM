import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
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
  Table,
  Tabs,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  ArrowLeftOutlined,
  CheckOutlined,
  DownloadOutlined,
  EditOutlined,
  PlusOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { api } from '../../api/client';
import { ExampleAlert } from '../../components/ExampleTag';
import { useAuthStore } from '../../stores/auth';
import { useRoleOptions } from '../../utils/roleOptions';
import FlowDiagram from '../../components/FlowDiagram';
import GanttChart from '../../components/GanttChart';
import ImportButtons from '../../components/ImportButtons';
import type {
  AllowedTransition,
  AttachmentItem,
  CostEntry,
  Member,
  Milestone,
  Portfolio,
  ProjectDetail as ProjectDetailData,
  Risk,
  RiskGrade,
  ServiceItem,
  WbsStatus,
  WbsTask,
} from '../../api/types';
import { RISK_GRADES } from '../../api/types';
import { HealthDot, RiskLevelTag, StatusBadge, fmt10k, fmtPct } from './shared';

const WBS_STATUSES: WbsStatus[] = ['未开始', '进行中', '已完成'];

const WBS_TAG_COLORS: Record<WbsStatus, string> = {
  未开始: 'default',
  进行中: 'processing',
  已完成: 'success',
};

function formatSize(size: number): string {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${size} B`;
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
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const { roleLabel } = useRoleOptions();

  const [detail, setDetail] = useState<ProjectDetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const [wbs, setWbs] = useState<WbsTask[]>([]);
  const [milestones, setMilestones] = useState<Milestone[]>([]);
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
    void Promise.all([loadDetail(), loadWbs(), loadMilestones(), loadRisks(), loadCosts(), loadAttachments()]).finally(
      () => setLoading(false),
    );
  }, [loadDetail, loadWbs, loadMilestones, loadRisks, loadCosts, loadAttachments]);

  useEffect(() => {
    api
      .getList<Member>('/members', { page: 1, page_size: 999 })
      .then((res) => setMembers(res.items))
      .catch(() => undefined);
  }, []);

  const canEdit = detail?.can_edit ?? false;
  /** 示例数据只读：兜底隐藏 can_edit 覆盖不到的写入口（任务负责人路径/最新动态/附件上传） */
  const isExample = detail?.is_example === true;
  const isFinal = detail?.status === 'closed' || detail?.status === 'cancelled';
  const memberOptions = useMemo(
    () =>
      members.map((m) => ({
        value: m.id,
        label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
      })),
    [members],
  );

  // ---------- 状态流转 ----------
  const runTransition = (t: AllowedTransition) => {
    Modal.confirm({
      title: `确认执行「${t.to_name}」？`,
      content: `项目状态将变更为「${t.to_name}」。`,
      onOk: async () => {
        await api.post(`/projects/${id}/transition`, { to: t.to, fields: {} });
        message.success('操作成功');
        void loadDetail();
      },
    });
  };

  // ---------- 编辑基本信息 ----------
  const [editOpen, setEditOpen] = useState(false);
  const [editSaving, setEditSaving] = useState(false);
  const [editForm] = Form.useForm();
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [serviceItems, setServiceItems] = useState<ServiceItem[]>([]);

  const openEdit = () => {
    if (!detail) return;
    editForm.setFieldsValue({
      name: detail.name,
      pm: detail.pm,
      planned: [dayjs(detail.planned_start), dayjs(detail.planned_end)],
      portfolio_id: detail.portfolio_id ?? undefined,
      service_item_id: detail.service_item_id ?? undefined,
      budget_10k: detail.budget_10k ?? undefined,
      description: detail.description ?? undefined,
    });
    setEditOpen(true);
    if (portfolios.length === 0) {
      api
        .getList<Portfolio>('/portfolios')
        .then((res) => setPortfolios(res.items))
        .catch(() => undefined);
    }
    if (serviceItems.length === 0) {
      api
        .getList<ServiceItem>('/service-items')
        .then((res) => setServiceItems(res.items))
        .catch(() => undefined);
    }
  };

  const submitEdit = async () => {
    const v = await editForm.validateFields();
    setEditSaving(true);
    try {
      await api.patch(`/projects/${id}`, {
        name: v.name,
        pm: v.pm,
        planned_start: (v.planned[0] as Dayjs).format('YYYY-MM-DD'),
        planned_end: (v.planned[1] as Dayjs).format('YYYY-MM-DD'),
        portfolio_id: v.portfolio_id ?? null,
        service_item_id: v.service_item_id ?? null,
        budget_10k: v.budget_10k ?? null,
        description: v.description || null,
      });
      message.success('项目信息已更新');
      setEditOpen(false);
      void loadDetail();
    } catch {
      // 已统一提示
    } finally {
      setEditSaving(false);
    }
  };

  // ---------- 最新动态 ----------
  const saveLatestUpdate = async (text: string) => {
    if (!detail || text === (detail.latest_update ?? '')) return;
    try {
      await api.patch(`/projects/${id}`, { latest_update: text });
      message.success('最新动态已更新');
      void loadDetail();
    } catch {
      // 已统一提示
    }
  };

  // ---------- 里程碑 ----------
  const [msModalOpen, setMsModalOpen] = useState(false);
  const [msSaving, setMsSaving] = useState(false);
  const [msForm] = Form.useForm();

  const submitMilestone = async () => {
    const v = await msForm.validateFields();
    setMsSaving(true);
    try {
      await api.post(`/projects/${id}/milestones`, {
        name: v.name,
        target_date: (v.target_date as Dayjs).format('YYYY-MM-DD'),
        description: v.description || null,
      });
      message.success('里程碑已创建');
      setMsModalOpen(false);
      void loadMilestones();
      void loadDetail();
    } catch {
      // 已统一提示
    } finally {
      setMsSaving(false);
    }
  };

  const achieveMilestone = async (m: Milestone) => {
    try {
      await api.post(`/milestones/${m.id}/achieve`);
      message.success(`里程碑「${m.name}」已达成`);
      void loadMilestones();
      void loadDetail();
    } catch {
      // 已统一提示
    }
  };

  const deleteMilestone = async (m: Milestone) => {
    try {
      await api.delete(`/milestones/${m.id}`);
      message.success('里程碑已删除');
      void loadMilestones();
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
        description: task.description ?? undefined,
        deliverable: task.deliverable ?? undefined,
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
      description: v.description || null,
      deliverable: v.deliverable || null,
      predecessor_ids: v.predecessor_ids ?? [],
    };
    setTaskSaving(true);
    try {
      if (taskModal.mode === 'edit' && taskModal.task) {
        await api.patch(`/wbs/${taskModal.task.id}`, base);
        message.success('任务已更新');
      } else {
        await api.post(`/projects/${id}/wbs`, {
          ...base,
          parent_task_id: taskModal.parent?.id ?? null,
        });
        message.success('任务已创建');
      }
      setTaskModal(null);
      void loadWbs();
      void loadDetail();
    } catch {
      // 已统一提示
    } finally {
      setTaskSaving(false);
    }
  };

  const changeTaskStatus = async (task: WbsTask, status: WbsStatus) => {
    try {
      await api.patch(`/wbs/${task.id}`, { status });
      message.success('任务状态已更新');
      void loadWbs();
      void loadDetail();
    } catch {
      // 403 等由拦截器统一中文提示
    }
  };

  const deleteTask = async (task: WbsTask) => {
    try {
      await api.delete(`/wbs/${task.id}`);
      message.success('任务已删除');
      void loadWbs();
      void loadDetail();
    } catch {
      // 已统一提示（有子任务时后端返回 400）
    }
  };

  /** 任务状态可编辑：有 projects.edit 或本人是任务负责人；示例数据一律只读 */
  const canChangeStatus = (task: WbsTask): boolean =>
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
      message.success('成本明细已登记');
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
      message.success('成本明细已删除');
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
        message.success('风险已更新');
      } else {
        await api.post(`/projects/${id}/risks`, {
          title: v.title,
          probability: v.probability,
          impact: v.impact,
          mitigation: v.mitigation || null,
        });
        message.success('风险已登记');
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
        <Typography.Text type="secondary">项目不存在或无权查看</Typography.Text>
      </Card>
    );
  }

  // ----- 概述 -----
  const overviewTab = (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Descriptions column={2} size="small" bordered>
        <Descriptions.Item label="项目经理">{detail.pm_name ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="所属组合">{detail.portfolio_name ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="计划起止">
          {detail.planned_start} ~ {detail.planned_end}
        </Descriptions.Item>
        <Descriptions.Item label="实际起止">
          {detail.actual_start ?? '-'} ~ {detail.actual_end ?? '-'}
        </Descriptions.Item>
        <Descriptions.Item label="预算">{fmt10k(detail.budget_10k)}</Descriptions.Item>
        <Descriptions.Item label="实际成本">{fmt10k(detail.actual_cost_10k)}</Descriptions.Item>
        <Descriptions.Item label="预算执行率">
          <span style={detail.budget_usage != null && detail.budget_usage > 100 ? { color: '#ff4d4f' } : undefined}>
            {fmtPct(detail.budget_usage)}
          </span>
        </Descriptions.Item>
        <Descriptions.Item label="SPI / CPI">
          {detail.spi ?? '-'} / {detail.cpi ?? '-'}
        </Descriptions.Item>
        <Descriptions.Item label="进度偏差">
          {detail.deviation == null ? (
            '-'
          ) : (
            <span style={detail.deviation > 15 ? { color: '#ff4d4f' } : undefined}>{detail.deviation} 个百分点</span>
          )}
        </Descriptions.Item>
        <Descriptions.Item label="任务 / 里程碑 / 风险">
          任务 {detail.task_done}/{detail.task_total} · 里程碑 {detail.milestone_total}
          {detail.milestone_overdue > 0 && <span style={{ color: '#ff4d4f' }}>（逾期 {detail.milestone_overdue}）</span>}
          {' '}· 开放风险 {detail.open_risks}
          {detail.red_risks > 0 && <span style={{ color: '#ff4d4f' }}>（红色 {detail.red_risks}）</span>}
        </Descriptions.Item>
        <Descriptions.Item label="描述" span={2}>
          <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
            {detail.description || '-'}
          </Typography.Paragraph>
        </Descriptions.Item>
      </Descriptions>

      <Card title="最新动态" size="small">
        <Typography.Paragraph
          style={{ marginBottom: 0 }}
          editable={
            canEdit && !isExample
              ? {
                  text: detail.latest_update ?? '',
                  maxLength: 200,
                  tooltip: '编辑最新动态（一句话）',
                  onChange: (v) => void saveLatestUpdate(v),
                }
              : false
          }
        >
          {detail.latest_update || '暂无动态'}
        </Typography.Paragraph>
      </Card>

      <Card title="关联需求" size="small">
        {(detail.linked_requirements ?? []).length === 0 ? (
          <Typography.Text type="secondary">
            暂无关联需求（在需求详情的实现阶段可挂接本项目）
          </Typography.Text>
        ) : (
          <Space direction="vertical" size={4} style={{ width: '100%' }}>
            {(detail.linked_requirements ?? []).map((r) => (
              <Space key={r.id} size={8}>
                <Link to={`/requirements/${r.id}`}>{r.requirement_code}</Link>
                <span>{r.title}</span>
                {r.moscow && <Tag>{r.moscow}</Tag>}
                <Tag>{r.status_name}</Tag>
              </Space>
            ))}
          </Space>
        )}
      </Card>

      <Card title="进度" size="small">
        {detail.progress == null ? (
          <Typography.Text type="secondary">暂无 WBS 任务，无法计算进度</Typography.Text>
        ) : (
          <>
            <Progress percent={detail.progress} format={(p) => `${p ?? 0}%`} />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              计划进度 {fmtPct(detail.planned_progress)}
              {detail.deviation != null && ` · 偏差 ${detail.deviation} 个百分点`}
              {detail.spi != null && ` · SPI ${detail.spi}`}
            </Typography.Text>
          </>
        )}
      </Card>
    </Space>
  );

  // ----- 进度 -----
  const msColumns: ColumnsType<Milestone> = [
    { title: '名称', dataIndex: 'name', ellipsis: true },
    {
      title: '目标日期',
      dataIndex: 'target_date',
      width: 160,
      render: (v: string, r) => (
        <Space size={4}>
          {v}
          {r.overdue && <Tag color="red">逾期</Tag>}
        </Space>
      ),
    },
    {
      title: '达成时间',
      dataIndex: 'achieved_at',
      width: 130,
      render: (v: string | null) => (v ? <Tag color="green">{v}</Tag> : '-'),
    },
    { title: '说明', dataIndex: 'description', ellipsis: true, render: (v) => v || '-' },
    ...(canEdit
      ? [
          {
            title: '操作',
            key: 'action',
            width: 140,
            render: (_: unknown, r: Milestone) => (
              <Space size={0}>
                {!r.achieved_at && (
                  <Popconfirm title={`确认里程碑「${r.name}」已达成？`} onConfirm={() => void achieveMilestone(r)}>
                    <Button type="link" size="small" icon={<CheckOutlined />}>
                      达成
                    </Button>
                  </Popconfirm>
                )}
                <Popconfirm title="确认删除该里程碑？" onConfirm={() => void deleteMilestone(r)}>
                  <Button type="link" size="small" danger>
                    删除
                  </Button>
                </Popconfirm>
              </Space>
            ),
          } as ColumnsType<Milestone>[number],
        ]
      : []),
  ];

  const wbsColumns: ColumnsType<WbsNode> = [
    { title: '编码', dataIndex: 'wbs_code', width: 90 },
    { title: '名称', dataIndex: 'name', ellipsis: true },
    { title: '负责人', dataIndex: 'assignee_name', width: 100, render: (v) => v || '-' },
    {
      title: '起止',
      key: 'dates',
      width: 200,
      render: (_, r) => `${r.start_date} ~ ${r.end_date}`,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (v: WbsStatus, r) =>
        canChangeStatus(r) ? (
          <Select
            size="small"
            value={v}
            style={{ width: 92 }}
            options={WBS_STATUSES.map((s) => ({ value: s, label: s }))}
            onChange={(s) => void changeTaskStatus(r, s)}
          />
        ) : (
          <Tag color={WBS_TAG_COLORS[v]}>{v}</Tag>
        ),
    },
    { title: '交付物', dataIndex: 'deliverable', width: 150, ellipsis: true, render: (v) => v || '-' },
    ...(canEdit
      ? [
          {
            title: '操作',
            key: 'action',
            width: 190,
            render: (_: unknown, r: WbsNode) => (
              <Space size={0}>
                <Button type="link" size="small" onClick={() => openTaskModal('edit', r)}>
                  编辑
                </Button>
                <Button type="link" size="small" onClick={() => openTaskModal('create', undefined, r)}>
                  加子任务
                </Button>
                <Popconfirm title="确认删除该任务？" onConfirm={() => void deleteTask(r)}>
                  <Button type="link" size="small" danger>
                    删除
                  </Button>
                </Popconfirm>
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
                void loadDetail();
              }}
              buttonText="导入 WBS 与里程碑"
            />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              模板含「WBS任务」「里程碑」两个工作表；上级/前置任务按名称挂接，导入后自动生成层级编码与甘特依赖线
            </Typography.Text>
          </Space>
        </Card>
      )}
      <Card
        title="里程碑"
        size="small"
        extra={
          canEdit && (
            <Button
              size="small"
              icon={<PlusOutlined />}
              onClick={() => {
                msForm.resetFields();
                setMsModalOpen(true);
              }}
            >
              新建里程碑
            </Button>
          )
        }
      >
        <Table<Milestone>
          size="small"
          rowKey="id"
          columns={msColumns}
          dataSource={milestones}
          pagination={false}
          locale={{ emptyText: '暂无里程碑' }}
        />
      </Card>

      <Card
        title="WBS 任务"
        size="small"
        extra={
          canEdit && (
            <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => openTaskModal('create')}>
              新建任务
            </Button>
          )
        }
      >
        <Table<WbsNode>
          size="small"
          rowKey="id"
          columns={wbsColumns}
          dataSource={wbsTree}
          pagination={false}
          scroll={{ x: 1000 }}
          expandable={{
            expandedRowKeys: expandedKeys,
            onExpandedRowsChange: setExpandedKeys,
          }}
          locale={{ emptyText: '暂无任务，可通过「新建任务」或章程导入生成' }}
        />
      </Card>

      <Card title="甘特图" size="small">
        <GanttChart
          tasks={wbs}
          milestones={milestones}
          rangeStart={detail.planned_start}
          rangeEnd={detail.planned_end}
        />
      </Card>
    </Space>
  );

  // ----- 成本 -----
  const costColumns: ColumnsType<CostEntry> = [
    { title: '日期', dataIndex: 'entry_date', width: 130 },
    { title: '金额（万元）', dataIndex: 'amount_10k', width: 130 },
    { title: '说明', dataIndex: 'note', ellipsis: true, render: (v) => v || '-' },
    ...(canEdit
      ? [
          {
            title: '操作',
            key: 'action',
            width: 80,
            render: (_: unknown, r: CostEntry) => (
              <Popconfirm title="确认删除该成本明细？" onConfirm={() => void deleteCost(r)}>
                <Button type="link" size="small" danger>
                  删除
                </Button>
              </Popconfirm>
            ),
          } as ColumnsType<CostEntry>[number],
        ]
      : []),
  ];

  const costTab = (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Row gutter={16}>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title="预算（万元）" value={detail.budget_10k ?? '-'} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title="实际成本（万元）" value={detail.actual_cost_10k} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic
              title="预算执行率"
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
        title="成本明细"
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
              新增明细
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
          locale={{ emptyText: '暂无成本明细' }}
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
    { title: '标题', dataIndex: 'title', ellipsis: true },
    { title: '概率', dataIndex: 'probability', width: 70 },
    { title: '影响', dataIndex: 'impact', width: 70 },
    {
      title: '等级',
      key: 'level',
      width: 80,
      render: (_, r) => <RiskLevelTag probability={r.probability} impact={r.impact} />,
    },
    { title: '应对措施', dataIndex: 'mitigation', ellipsis: true, render: (v) => v || '-' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: Risk['status']) => <Tag color={v === '开放' ? 'orange' : 'default'}>{v}</Tag>,
    },
    ...(canEdit
      ? [
          {
            title: '操作',
            key: 'action',
            width: 70,
            render: (_: unknown, r: Risk) => (
              <Button type="link" size="small" onClick={() => openRiskModal('edit', r)}>
                编辑
              </Button>
            ),
          } as ColumnsType<Risk>[number],
        ]
      : []),
  ];

  const riskTab = (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card title="概率 × 影响矩阵（开放风险数）" size="small">
        <div style={{ display: 'grid', gridTemplateColumns: '90px repeat(3, 90px)', gap: 4, fontSize: 13 }}>
          <div />
          {RISK_GRADES.map((i) => (
            <div key={`h-${i}`} style={{ textAlign: 'center', color: 'rgba(0,0,0,0.45)' }}>
              影响·{i}
            </div>
          ))}
          {RISK_GRADES.map((p) => (
            <div key={`row-${p}`} style={{ display: 'contents' }}>
              <div style={{ lineHeight: '44px', color: 'rgba(0,0,0,0.45)' }}>概率·{p}</div>
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
        title="风险清单"
        size="small"
        extra={
          canEdit && (
            <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => openRiskModal('create')}>
              新建风险
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
          locale={{ emptyText: '暂无风险' }}
        />
      </Card>
    </Space>
  );

  // ----- 文档 -----
  const attachmentColumns: ColumnsType<AttachmentItem> = [
    {
      title: '文件名',
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
    { title: '大小', dataIndex: 'size', width: 100, render: (v: number) => formatSize(v) },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      width: 160,
      render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'),
    },
  ];

  const docsTab = (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Alert
        type="info"
        showIcon
        message="章程导入"
        description={
          <span>
            如需通过《项目章程》.docx 快速创建项目（自动生成 WBS/里程碑/风险草稿），请前往
            <Link to="/projects">项目列表页</Link>使用「章程导入」向导。本页附件仅作为项目文档存档。
          </span>
        }
      />
      <Card
        title="附件"
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
                    message.success('附件已上传');
                    void loadAttachments();
                  })
                  .catch((e) => onError?.(e as Error));
              }}
            >
              <Button size="small" type="primary" icon={<UploadOutlined />}>
                上传附件
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
          locale={{ emptyText: '暂无附件' }}
        />
      </Card>
    </Space>
  );

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {isExample && <ExampleAlert />}
      {/* 头部 */}
      <Card>
        <Space style={{ width: '100%', justifyContent: 'space-between', flexWrap: 'wrap' }}>
          <Space size="middle" wrap>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/projects')}>
              返回
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
                <Button icon={<EditOutlined />} onClick={openEdit}>
                  编辑
                </Button>
              )}
              {(detail.allowed_transitions ?? []).map((t) => (
                <Button
                  key={t.to}
                  type={t.to === 'cancelled' ? 'default' : 'primary'}
                  danger={t.to === 'cancelled'}
                  onClick={() => runTransition(t)}
                >
                  {t.to_name}
                </Button>
              ))}
            </Space>
          )}
        </Space>
      </Card>

      {/* 流程示意 */}
      {detail.process && detail.process.steps?.length > 0 && (
        <Card title={`流程：${detail.process.definition_name}`} size="small">
          <FlowDiagram
            steps={detail.process.steps}
            roleLabel={roleLabel}
            currentSeq={detail.process.current_step_seq}
          />
        </Card>
      )}

      <Card>
        <Tabs
          items={[
            { key: 'overview', label: '概述', children: overviewTab },
            { key: 'progress', label: '进度', children: progressTab },
            { key: 'cost', label: '成本', children: costTab },
            { key: 'risk', label: '风险', children: riskTab },
            { key: 'docs', label: '文档', children: docsTab },
          ]}
        />
      </Card>

      {/* 编辑基本信息 Modal */}
      <Modal
        title="编辑项目信息"
        open={editOpen}
        width={560}
        onOk={() => void submitEdit()}
        confirmLoading={editSaving}
        onCancel={() => setEditOpen(false)}
        destroyOnClose
      >
        <Form form={editForm} layout="vertical">
          <Form.Item
            name="name"
            label="项目名称"
            rules={[
              { required: true, message: '请输入项目名称' },
              { min: 2, message: '至少 2 个字符' },
            ]}
          >
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="pm" label="项目经理" rules={[{ required: true, message: '请选择项目经理' }]}>
            <Select showSearch optionFilterProp="label" options={memberOptions} />
          </Form.Item>
          <Form.Item name="planned" label="计划起止" rules={[{ required: true, message: '请选择计划起止日期' }]}>
            <DatePicker.RangePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="portfolio_id" label="所属组合">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              options={portfolios.map((p) => ({ value: p.id, label: p.name }))}
            />
          </Form.Item>
          <Form.Item name="service_item_id" label="关联服务项">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              options={serviceItems.map((i) => ({
                value: i.id,
                label: `${i.name}（${i.catalog_name ?? i.item_code}）`,
              }))}
            />
          </Form.Item>
          <Form.Item name="budget_10k" label="预算（万元）">
            <InputNumber min={0} precision={2} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} maxLength={2000} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 新建里程碑 Modal */}
      <Modal
        title="新建里程碑"
        open={msModalOpen}
        onOk={() => void submitMilestone()}
        confirmLoading={msSaving}
        onCancel={() => setMsModalOpen(false)}
        destroyOnClose
      >
        <Form form={msForm} layout="vertical" preserve={false}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入里程碑名称' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="target_date" label="目标日期" rules={[{ required: true, message: '请选择目标日期' }]}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 新建/编辑任务 Modal */}
      <Modal
        title={
          taskModal?.mode === 'edit'
            ? `编辑任务：${taskModal.task?.name ?? ''}`
            : taskModal?.parent
              ? `新建子任务（父任务：${taskModal.parent.name}）`
              : '新建任务'
        }
        open={!!taskModal}
        onOk={() => void submitTask()}
        confirmLoading={taskSaving}
        onCancel={() => setTaskModal(null)}
        destroyOnClose
      >
        <Form form={taskForm} layout="vertical" preserve={false}>
          <Form.Item name="name" label="任务名称" rules={[{ required: true, message: '请输入任务名称' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="assignee" label="负责人" rules={[{ required: true, message: '请选择负责人' }]}>
            <Select showSearch optionFilterProp="label" options={memberOptions} />
          </Form.Item>
          <Form.Item name="dates" label="起止日期" rules={[{ required: true, message: '请选择起止日期' }]}>
            <DatePicker.RangePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="deliverable" label="交付物">
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item
            name="predecessor_ids"
            label="前置任务"
            extra="前置任务完成后本任务才应开始；甘特图中以虚线箭头表示"
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
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 新增成本明细 Modal */}
      <Modal
        title="新增成本明细"
        open={costModalOpen}
        onOk={() => void submitCost()}
        confirmLoading={costSaving}
        onCancel={() => setCostModalOpen(false)}
        destroyOnClose
      >
        <Form form={costForm} layout="vertical" preserve={false}>
          <Form.Item name="entry_date" label="日期" rules={[{ required: true, message: '请选择日期' }]}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="amount_10k"
            label="金额（万元）"
            rules={[{ required: true, message: '请输入金额（万元）' }]}
          >
            <InputNumber min={0.0001} precision={4} style={{ width: '100%' }} placeholder="必须大于 0" />
          </Form.Item>
          <Form.Item name="note" label="说明">
            <Input maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 新建/编辑风险 Modal */}
      <Modal
        title={riskModal?.mode === 'edit' ? '编辑风险' : '新建风险'}
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
          <Form.Item name="title" label="风险标题" rules={[{ required: true, message: '请输入风险标题' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Space size={16}>
            <Form.Item name="probability" label="概率" rules={[{ required: true }]} style={{ width: 120 }}>
              <Select options={RISK_GRADES.map((g) => ({ value: g, label: g }))} />
            </Form.Item>
            <Form.Item name="impact" label="影响" rules={[{ required: true }]} style={{ width: 120 }}>
              <Select options={RISK_GRADES.map((g) => ({ value: g, label: g }))} />
            </Form.Item>
            {riskModal?.mode === 'edit' && (
              <Form.Item name="status" label="状态" style={{ width: 120 }}>
                <Select options={['开放', '已关闭'].map((s) => ({ value: s, label: s }))} />
              </Form.Item>
            )}
          </Space>
          <Form.Item name="mitigation" label="应对措施">
            <Input.TextArea rows={3} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );
}
