import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  Alert,
  Button,
  Card,
  Checkbox,
  DatePicker,
  Descriptions,
  Form,
  Input,
  Modal,
  Popconfirm,
  Progress,
  Select,
  Space,
  Spin,
  Steps,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  ArrowLeftOutlined,
  BookOutlined,
  DeleteOutlined,
  EditOutlined,
  ExportOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { api } from '../../api/client';
import { useAuthStore } from '../../stores/auth';
import { useRoleOptions } from '../../utils/roleOptions';
import FlowDiagram from '../../components/FlowDiagram';
import type {
  AcceptanceCriterion,
  AllowedTransition,
  BusinessDomain,
  MasterDataItem,
  Member,
  ProjectRow,
  RequirementDetail as RequirementDetailData,
  RequirementTask,
  RequirementTaskStatus,
} from '../../api/types';
import {
  MOSCOW_KEYS,
  MOSCOW_META,
  REQ_TASK_STATUSES,
  REQ_TASK_STATUS_COLORS,
  REQ_TYPES,
} from '../../api/types';
import { MoscowTag, ReqStatusBadge, fmtDt } from './shared';

const MOSCOW_OPTIONS = MOSCOW_KEYS.map((k) => ({ value: k, label: MOSCOW_META[k].label }));

export default function RequirementDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const { roleLabel } = useRoleOptions();

  const [detail, setDetail] = useState<RequirementDetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const [members, setMembers] = useState<Member[]>([]);
  const [projects, setProjects] = useState<ProjectRow[]>([]);

  // ---------- 加载 ----------
  const load = useCallback(async () => {
    if (!id) return;
    try {
      setDetail(await api.get<RequirementDetailData>(`/requirements/${id}`));
    } catch {
      // 已统一提示
    }
  }, [id]);

  useEffect(() => {
    setLoading(true);
    void load().finally(() => setLoading(false));
  }, [load]);

  // 编辑者才需要人员/项目下拉（提出人只读视角不请求）
  const canEdit = detail?.can_edit ?? false;
  useEffect(() => {
    if (!canEdit) return;
    api
      .getList<Member>('/members', { page: 1, page_size: 999 })
      .then((res) => setMembers(res.items))
      .catch(() => undefined);
    api
      .getList<ProjectRow>('/projects', { page: 1, page_size: 200 })
      .then((res) => setProjects(res.items))
      .catch(() => undefined);
  }, [canEdit]);

  const memberOptions = useMemo(
    () =>
      members.map((m) => ({
        value: m.id,
        label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
      })),
    [members],
  );

  const projectOptions = useMemo(
    () => projects.map((p) => ({ value: p.id, label: `${p.project_code} ${p.name}` })),
    [projects],
  );

  // ---------- 通用 PATCH ----------
  const patchField = async (patch: Record<string, unknown>, okMsg = '已保存') => {
    try {
      await api.patch(`/requirements/${id}`, patch);
      message.success(okMsg);
      void load();
    } catch {
      // 已统一提示
    }
  };

  // ---------- 状态流转 ----------
  const [closeTrans, setCloseTrans] = useState<AllowedTransition | null>(null);
  const [closeSaving, setCloseSaving] = useState(false);
  const [closeForm] = Form.useForm();

  const runTransition = (t: AllowedTransition) => {
    if (!detail) return;
    if (t.to === 'closed') {
      closeForm.setFieldsValue({ closure_note: detail.closure_note ?? undefined });
      setCloseTrans(t);
      return;
    }
    const needAnalysis = t.to === 'implementing' && (!detail.moscow || !detail.owner);
    Modal.confirm({
      title: `确认执行「${t.to_name}」？`,
      content: needAnalysis
        ? '提示：MoSCoW 优先级与负责人尚未填写，进入实现将被阶段门拦截，请先在「分析」区完成。'
        : `需求状态将变更为「${t.to_name}」。`,
      onOk: async () => {
        await api.post(`/requirements/${id}/transition`, { to: t.to, fields: {} });
        message.success('操作成功');
        void load();
      },
    });
  };

  const submitClose = async () => {
    const v = await closeForm.validateFields();
    setCloseSaving(true);
    try {
      await api.post(`/requirements/${id}/transition`, {
        to: 'closed',
        fields: v.closure_note ? { closure_note: v.closure_note } : {},
      });
      message.success('需求已关闭');
      setCloseTrans(null);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setCloseSaving(false);
    }
  };

  // ---------- 编辑基本信息 ----------
  const [editOpen, setEditOpen] = useState(false);
  const [editSaving, setEditSaving] = useState(false);
  const [editForm] = Form.useForm();
  const [domains, setDomains] = useState<BusinessDomain[]>([]);
  const [sources, setSources] = useState<MasterDataItem[]>([]);

  const openEdit = () => {
    if (!detail) return;
    editForm.setFieldsValue({
      title: detail.title,
      req_type: detail.req_type,
      business_domain_id: detail.business_domain_id,
      source: detail.source ?? undefined,
      description: detail.description,
      remarks: detail.remarks ?? undefined,
    });
    setEditOpen(true);
    if (domains.length === 0) {
      api
        .getList<BusinessDomain>('/admin/business-domains')
        .then((res) => setDomains(res.items.filter((d) => d.active)))
        .catch(() => undefined);
    }
    if (sources.length === 0) {
      api
        .getList<MasterDataItem>('/admin/master-data', {
          category: 'requirement_source',
          page: 1,
          page_size: 999,
        })
        .then((res) => setSources(res.items.filter((s) => s.active !== false)))
        .catch(() => undefined);
    }
  };

  const submitEdit = async () => {
    const v = await editForm.validateFields();
    setEditSaving(true);
    try {
      await api.patch(`/requirements/${id}`, {
        title: v.title,
        req_type: v.req_type,
        business_domain_id: v.business_domain_id,
        source: v.source ?? null,
        description: v.description,
        remarks: v.remarks || null,
      });
      message.success('基本信息已更新');
      setEditOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setEditSaving(false);
    }
  };

  // ---------- 验收标准（全量 PATCH） ----------
  const [newCriterion, setNewCriterion] = useState('');

  const saveCriteria = async (list: AcceptanceCriterion[], okMsg: string) => {
    await patchField({ acceptance_criteria: list }, okMsg);
  };

  const addCriterion = () => {
    if (!detail) return;
    const text = newCriterion.trim();
    if (!text) return;
    setNewCriterion('');
    void saveCriteria([...(detail.acceptance_criteria ?? []), { text, checked: false }], '验收标准已添加');
  };

  // ---------- 实现阶段：任务 ----------
  const [taskOpen, setTaskOpen] = useState(false);
  const [taskSaving, setTaskSaving] = useState(false);
  const [taskForm] = Form.useForm();

  const submitTask = async () => {
    const v = await taskForm.validateFields();
    setTaskSaving(true);
    try {
      await api.post(`/requirements/${id}/tasks`, {
        name: v.name,
        assignee: v.assignee,
        plan_date: v.plan_date ? (v.plan_date as Dayjs).format('YYYY-MM-DD') : null,
      });
      message.success('任务已添加');
      setTaskOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setTaskSaving(false);
    }
  };

  const changeTaskStatus = async (task: RequirementTask, status: RequirementTaskStatus) => {
    try {
      await api.patch(`/requirements/tasks/${task.id}`, { status });
      message.success('任务状态已更新');
      void load();
    } catch {
      // 403 等由拦截器统一中文提示
    }
  };

  const deleteTask = async (task: RequirementTask) => {
    try {
      await api.delete(`/requirements/tasks/${task.id}`);
      message.success('任务已删除');
      void load();
    } catch {
      // 已统一提示
    }
  };

  // ---------- 关闭收尾：转出 ----------
  const [problemOpen, setProblemOpen] = useState(false);
  const [problemSaving, setProblemSaving] = useState(false);
  const [problemForm] = Form.useForm();

  const submitProblem = async () => {
    const v = await problemForm.validateFields();
    setProblemSaving(true);
    try {
      const res = await api.post<{ problem_id: string; problem_code: string }>(
        `/requirements/${id}/to-problem`,
        { title: v.title || null, description: v.description },
      );
      setProblemOpen(false);
      void load();
      Modal.confirm({
        title: `已转出遗留问题 ${res.problem_code}`,
        content: '问题单已创建并进入问题管理跟踪，可在「已转出清单」中随时查看。',
        okText: '前往问题详情',
        cancelText: '留在本页',
        onOk: () => navigate(`/itsm/problems/${res.problem_id}`),
      });
    } catch {
      // 已统一提示
    } finally {
      setProblemSaving(false);
    }
  };

  const runToKnowledge = () => {
    Modal.confirm({
      title: '确认沉淀为知识？',
      content: '将根据需求背景、解决方案与验收标准自动生成知识草稿，生成后跳转查看。',
      onOk: async () => {
        const res = await api.post<{ article_id: string; article_code: string }>(
          `/requirements/${id}/to-knowledge`,
        );
        message.success(`知识草稿 ${res.article_code} 已生成`);
        navigate(`/itsm/knowledge/${res.article_id}`);
      },
    });
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
        <Typography.Text type="secondary">需求不存在或无权查看</Typography.Text>
      </Card>
    );
  }

  const st = detail.status;
  const isFinal = st === 'closed' || st === 'cancelled';
  /** PATCH 类编辑：终态（closed/cancelled）后端拒绝，一律只读 */
  const canEditNow = canEdit && !isFinal;
  const reachedAnalyzing = !!detail.analyzing_at || ['analyzing', 'implementing', 'closed'].includes(st);
  const reachedImplementing = !!detail.implementing_at || ['implementing', 'closed'].includes(st);
  const showClosure = st === 'implementing' || st === 'closed';

  const criteria = detail.acceptance_criteria ?? [];
  const checkedCount = criteria.filter((c) => c.checked).length;
  const pendingAcceptance = criteria.length - checkedCount;

  const canChangeTaskStatus = (t: RequirementTask): boolean =>
    !isFinal && (canEdit || (!!user?.person_id && user.person_id === t.assignee));

  // ----- 阶段进度条 -----
  const currentStep = st === 'closed' ? 3 : reachedImplementing ? 2 : reachedAnalyzing ? 1 : 0;
  const stepItems = [
    { title: '登记', description: fmtDt(detail.registered_at) },
    { title: '分析', description: fmtDt(detail.analyzing_at) },
    { title: '实现', description: fmtDt(detail.implementing_at) },
    {
      title: '关闭',
      description: detail.closed_at ? (
        <>
          {fmtDt(detail.closed_at)}
          {detail.lead_days != null && <div>交付周期 {detail.lead_days} 天</div>}
        </>
      ) : undefined,
    },
  ];

  // ----- 任务表 -----
  const taskColumns: ColumnsType<RequirementTask> = [
    { title: '任务名称', dataIndex: 'name', ellipsis: true },
    { title: '负责人', dataIndex: 'assignee_name', width: 110, render: (v) => v || '-' },
    { title: '计划日期', dataIndex: 'plan_date', width: 110, render: (v) => v || '-' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (v: RequirementTaskStatus, r) =>
        canChangeTaskStatus(r) ? (
          <Select
            size="small"
            value={v}
            style={{ width: 96 }}
            options={REQ_TASK_STATUSES.map((s) => ({ value: s, label: s }))}
            onChange={(s) => void changeTaskStatus(r, s)}
          />
        ) : (
          <Tag color={REQ_TASK_STATUS_COLORS[v]}>{v}</Tag>
        ),
    },
    { title: '完成时间', dataIndex: 'done_at', width: 150, render: (v) => fmtDt(v) ?? '-' },
    ...(canEditNow
      ? [
          {
            title: '操作',
            key: 'action',
            width: 80,
            render: (_: unknown, r: RequirementTask) => (
              <Popconfirm title="确认删除该任务？" onConfirm={() => void deleteTask(r)}>
                <Button type="link" size="small" danger>
                  删除
                </Button>
              </Popconfirm>
            ),
          } as ColumnsType<RequirementTask>[number],
        ]
      : []),
  ];

  const handoverEmpty = detail.handover.problems.length + detail.handover.articles.length === 0;

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {/* 头部 */}
      <Card>
        <Space style={{ width: '100%', justifyContent: 'space-between', flexWrap: 'wrap' }}>
          <Space size="middle" wrap>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/requirements')}>
              返回
            </Button>
            <Typography.Title level={4} style={{ margin: 0 }}>
              {detail.requirement_code} · {detail.title}
            </Typography.Title>
            <ReqStatusBadge status={detail.status} name={detail.status_name} />
            <MoscowTag value={detail.moscow} empty={null} />
          </Space>
          {canEdit && (
            <Space wrap>
              {(detail.allowed_transitions ?? []).map((t) => {
                const closeBlocked = t.to === 'closed' && pendingAcceptance > 0;
                const btn = (
                  <Button
                    type={t.to === 'cancelled' || t.to === 'on_hold' ? 'default' : 'primary'}
                    danger={t.to === 'cancelled'}
                    disabled={closeBlocked}
                    style={closeBlocked ? { pointerEvents: 'none' } : undefined}
                    onClick={() => runTransition(t)}
                  >
                    {t.to_name}
                  </Button>
                );
                return closeBlocked ? (
                  <Tooltip
                    key={t.to}
                    title={`还有 ${pendingAcceptance} 项验收标准未通过，全部勾选后才能关闭（有遗留可先「转出遗留问题」）`}
                  >
                    <span style={{ cursor: 'not-allowed' }}>{btn}</span>
                  </Tooltip>
                ) : (
                  <span key={t.to}>{btn}</span>
                );
              })}
            </Space>
          )}
        </Space>
      </Card>

      {/* 非常规状态说明 */}
      {st === 'on_hold' && (
        <Alert
          type="warning"
          showIcon
          message="需求已搁置"
          description="该需求已暂缓推进，阶段进度停留在搁置前的位置；可通过右上角操作恢复到「分析中」继续，或取消。"
        />
      )}
      {st === 'cancelled' && (
        <Alert type="info" showIcon message="需求已取消" description="该需求已终止，以下信息仅供查看。" />
      )}

      {/* 阶段进度条 */}
      <Card size="small">
        <Steps
          size="small"
          current={currentStep}
          status={st === 'closed' ? 'finish' : st === 'cancelled' ? 'error' : 'process'}
          items={stepItems}
        />
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

      {/* 登记信息 */}
      <Card
        title="登记信息"
        size="small"
        extra={
          canEditNow && (
            <Button size="small" icon={<EditOutlined />} onClick={openEdit}>
              编辑基本信息
            </Button>
          )
        }
      >
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="编号">{detail.requirement_code}</Descriptions.Item>
          <Descriptions.Item label="类型">
            <Tag>{detail.req_type}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="业务域">{detail.business_domain_name ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="来源">{detail.source || '-'}</Descriptions.Item>
          <Descriptions.Item label="提出人">{detail.requester_name ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="登记时间">{fmtDt(detail.registered_at) ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="描述" span={2}>
            <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
              {detail.description || '-'}
            </Typography.Paragraph>
          </Descriptions.Item>
          {detail.remarks && (
            <Descriptions.Item label="备注" span={2}>
              <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                {detail.remarks}
              </Typography.Paragraph>
            </Descriptions.Item>
          )}
        </Descriptions>
      </Card>

      {/* 分析（进入分析阶段后显示） */}
      {reachedAnalyzing && (
        <Card title="分析" size="small">
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="MoSCoW 优先级">
              {canEditNow ? (
                <Select
                  allowClear
                  placeholder="未评估"
                  value={detail.moscow ?? undefined}
                  style={{ width: 150 }}
                  options={MOSCOW_OPTIONS}
                  onChange={(v) => void patchField({ moscow: v ?? null }, '优先级已更新')}
                />
              ) : (
                <MoscowTag value={detail.moscow} empty="未评估" />
              )}
            </Descriptions.Item>
            <Descriptions.Item label="需求负责人">
              {canEditNow ? (
                <Select
                  allowClear
                  showSearch
                  placeholder="未指派"
                  optionFilterProp="label"
                  value={detail.owner ?? undefined}
                  style={{ minWidth: 180 }}
                  options={memberOptions}
                  onChange={(v) => void patchField({ owner: v ?? null }, '负责人已更新')}
                />
              ) : (
                detail.owner_name || '-'
              )}
            </Descriptions.Item>
            <Descriptions.Item label="目标日期">
              {canEditNow ? (
                <DatePicker
                  value={detail.target_date ? dayjs(detail.target_date) : null}
                  onChange={(d) =>
                    void patchField({ target_date: d ? d.format('YYYY-MM-DD') : null }, '目标日期已更新')
                  }
                />
              ) : (
                detail.target_date || '-'
              )}
            </Descriptions.Item>
            <Descriptions.Item label="解决方案" span={2}>
              <Typography.Paragraph
                style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}
                editable={
                  canEditNow
                    ? {
                        text: detail.solution ?? '',
                        autoSize: { minRows: 2 },
                        tooltip: '编辑解决方案',
                        onChange: (v) => {
                          if (v !== (detail.solution ?? '')) {
                            void patchField({ solution: v || null }, '解决方案已更新');
                          }
                        },
                      }
                    : false
                }
              >
                {detail.solution || '暂无'}
              </Typography.Paragraph>
            </Descriptions.Item>
          </Descriptions>

          {/* 验收标准清单 */}
          <div style={{ marginTop: 16 }}>
            <Space style={{ marginBottom: 8 }}>
              <Typography.Text strong>验收标准</Typography.Text>
              {criteria.length > 0 && (
                <Tag color={pendingAcceptance === 0 ? 'green' : 'orange'} style={{ marginInlineEnd: 0 }}>
                  {checkedCount}/{criteria.length} 已通过
                </Tag>
              )}
            </Space>
            {criteria.length === 0 && (
              <div>
                <Typography.Text type="secondary">
                  暂无验收标准{canEditNow ? '，可在下方添加（关闭前需全部勾选通过）' : ''}
                </Typography.Text>
              </div>
            )}
            {criteria.map((c, i) => (
              <div
                key={`${i}-${c.text}`}
                style={{ display: 'flex', alignItems: 'flex-start', gap: 8, padding: '4px 0' }}
              >
                <Checkbox
                  checked={c.checked}
                  disabled={!canEditNow}
                  onChange={(e) =>
                    void saveCriteria(
                      criteria.map((x, j) => (j === i ? { ...x, checked: e.target.checked } : x)),
                      e.target.checked ? '已通过该验收项' : '已取消通过',
                    )
                  }
                />
                <span style={{ flex: 1, ...(c.checked ? { color: 'rgba(0,0,0,0.45)' } : {}) }}>{c.text}</span>
                {canEditNow && (
                  <Button
                    type="text"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() =>
                      void saveCriteria(
                        criteria.filter((_, j) => j !== i),
                        '验收标准已删除',
                      )
                    }
                  />
                )}
              </div>
            ))}
            {canEditNow && (
              <Space.Compact style={{ width: '100%', maxWidth: 480, marginTop: 8 }}>
                <Input
                  value={newCriterion}
                  onChange={(e) => setNewCriterion(e.target.value)}
                  placeholder="新增验收标准，如：报表口径与财务一致"
                  maxLength={200}
                  onPressEnter={addCriterion}
                />
                <Button icon={<PlusOutlined />} onClick={addCriterion}>
                  添加
                </Button>
              </Space.Compact>
            )}
          </div>
        </Card>
      )}

      {/* 实现（进入实现阶段后显示） */}
      {reachedImplementing && (
        <Card
          title="实现"
          size="small"
          extra={
            canEditNow && (
              <Button
                size="small"
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => {
                  taskForm.resetFields();
                  setTaskOpen(true);
                }}
              >
                添加任务
              </Button>
            )
          }
        >
          <Descriptions column={2} size="small" bordered style={{ marginBottom: 16 }}>
            <Descriptions.Item label="关联项目">
              {canEditNow ? (
                <Space wrap>
                  <Select
                    allowClear
                    showSearch
                    placeholder="关联到项目（可选）"
                    optionFilterProp="label"
                    value={detail.project_id ?? undefined}
                    style={{ minWidth: 240 }}
                    options={projectOptions}
                    onChange={(v) => void patchField({ project_id: v ?? null }, '关联项目已更新')}
                  />
                  {detail.project_id && <Link to={`/projects/${detail.project_id}`}>查看项目</Link>}
                </Space>
              ) : detail.project_id ? (
                <Link to={`/projects/${detail.project_id}`}>{detail.project_name || '查看项目'}</Link>
              ) : (
                '-'
              )}
            </Descriptions.Item>
            <Descriptions.Item label="任务进度">
              {detail.task_total === 0 ? (
                <Typography.Text type="secondary">暂无任务</Typography.Text>
              ) : (
                <Progress
                  percent={detail.progress ?? 0}
                  style={{ minWidth: 180, marginBottom: 0 }}
                  format={() => `${detail.task_done}/${detail.task_total}`}
                />
              )}
            </Descriptions.Item>
          </Descriptions>

          <Table<RequirementTask>
            size="small"
            rowKey="id"
            columns={taskColumns}
            dataSource={detail.tasks}
            pagination={false}
            locale={{ emptyText: '暂无任务，可通过「添加任务」分解实现工作' }}
          />
        </Card>
      )}

      {/* 关闭收尾（实现中/已关闭显示） */}
      {showClosure && (
        <Card title="关闭收尾" size="small">
          {canEdit && (
            <Space wrap style={{ marginBottom: 16 }}>
              <Button
                icon={<ExportOutlined />}
                onClick={() => {
                  problemForm.resetFields();
                  setProblemOpen(true);
                }}
              >
                转出遗留问题
              </Button>
              <Button icon={<BookOutlined />} onClick={runToKnowledge}>
                沉淀知识
              </Button>
            </Space>
          )}

          <Typography.Text strong>已转出清单</Typography.Text>
          <div style={{ margin: '8px 0 16px' }}>
            {handoverEmpty ? (
              <Typography.Text type="secondary">暂无转出记录</Typography.Text>
            ) : (
              <Space direction="vertical" size={4}>
                {detail.handover.problems.map((p) => (
                  <div key={p.id}>
                    <Tag color="volcano">问题</Tag>
                    <Link to={`/itsm/problems/${p.id}`}>{p.problem_code}</Link>{' '}
                    <Typography.Text>{p.title}</Typography.Text>
                  </div>
                ))}
                {detail.handover.articles.map((a) => (
                  <div key={a.id}>
                    <Tag color="green">知识</Tag>
                    <Link to={`/itsm/knowledge/${a.id}`}>{a.article_code}</Link>{' '}
                    <Typography.Text>{a.title}</Typography.Text>
                  </div>
                ))}
              </Space>
            )}
          </div>

          <Typography.Text strong>关闭说明</Typography.Text>
          <Typography.Paragraph
            style={{ marginTop: 8, marginBottom: 0, whiteSpace: 'pre-wrap' }}
            editable={
              canEditNow
                ? {
                    text: detail.closure_note ?? '',
                    autoSize: { minRows: 2 },
                    tooltip: '编辑关闭说明（也可在执行「已关闭」时填写）',
                    onChange: (v) => {
                      if (v !== (detail.closure_note ?? '')) {
                        void patchField({ closure_note: v || null }, '关闭说明已更新');
                      }
                    },
                  }
                : false
            }
          >
            {detail.closure_note || '暂无'}
          </Typography.Paragraph>
        </Card>
      )}

      {/* 编辑基本信息 Modal */}
      <Modal
        title="编辑基本信息"
        open={editOpen}
        width={560}
        onOk={() => void submitEdit()}
        confirmLoading={editSaving}
        onCancel={() => setEditOpen(false)}
        destroyOnClose
      >
        <Form form={editForm} layout="vertical">
          <Form.Item
            name="title"
            label="需求标题"
            rules={[
              { required: true, message: '请输入需求标题' },
              { min: 2, message: '至少 2 个字符' },
            ]}
          >
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="req_type" label="需求类型" rules={[{ required: true, message: '请选择需求类型' }]}>
            <Select options={REQ_TYPES.map((t) => ({ value: t, label: t }))} />
          </Form.Item>
          <Form.Item
            name="business_domain_id"
            label="所属业务域"
            rules={[{ required: true, message: '请选择所属业务域' }]}
          >
            <Select showSearch optionFilterProp="label" options={domains.map((d) => ({ value: d.id, label: d.name }))} />
          </Form.Item>
          <Form.Item name="source" label="需求来源">
            <Select allowClear options={sources.map((s) => ({ value: s.name, label: s.name }))} />
          </Form.Item>
          <Form.Item name="description" label="需求描述" rules={[{ required: true, message: '请输入需求描述' }]}>
            <Input.TextArea rows={4} maxLength={2000} />
          </Form.Item>
          <Form.Item name="remarks" label="备注">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 关闭需求 Modal（closure_note 随流转 fields 提交） */}
      <Modal
        title="关闭需求"
        open={!!closeTrans}
        onOk={() => void submitClose()}
        confirmLoading={closeSaving}
        onCancel={() => setCloseTrans(null)}
        destroyOnClose
      >
        <Alert
          type={criteria.length > 0 ? 'success' : 'info'}
          showIcon
          style={{ marginBottom: 16 }}
          message={
            criteria.length > 0
              ? `验收标准已全部通过（${checkedCount}/${criteria.length}）`
              : '该需求未设置验收标准'
          }
          description="关闭后需求进入终态，不可再编辑；如有遗留事项请先「转出遗留问题」。"
        />
        <Form form={closeForm} layout="vertical">
          <Form.Item name="closure_note" label="关闭说明（可选）">
            <Input.TextArea rows={3} maxLength={1000} placeholder="交付结果、遗留事项处理方式等" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 添加任务 Modal */}
      <Modal
        title="添加任务"
        open={taskOpen}
        onOk={() => void submitTask()}
        confirmLoading={taskSaving}
        onCancel={() => setTaskOpen(false)}
        destroyOnClose
      >
        <Form form={taskForm} layout="vertical" preserve={false}>
          <Form.Item name="name" label="任务名称" rules={[{ required: true, message: '请输入任务名称' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="assignee" label="负责人" rules={[{ required: true, message: '请选择负责人' }]}>
            <Select showSearch optionFilterProp="label" placeholder="选择人员" options={memberOptions} />
          </Form.Item>
          <Form.Item name="plan_date" label="计划日期">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 转出遗留问题 Modal */}
      <Modal
        title="转出遗留问题"
        open={problemOpen}
        onOk={() => void submitProblem()}
        confirmLoading={problemSaving}
        onCancel={() => setProblemOpen(false)}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="将遗留事项转为问题单继续跟踪，需求可正常关闭。"
        />
        <Form form={problemForm} layout="vertical" preserve={false}>
          <Form.Item name="title" label="问题标题" extra={`不填则默认为「[需求遗留] ${detail.title}」`}>
            <Input maxLength={200} placeholder="（可选）" />
          </Form.Item>
          <Form.Item name="description" label="问题描述" rules={[{ required: true, message: '请描述遗留问题' }]}>
            <Input.TextArea rows={4} maxLength={2000} placeholder="遗留了什么、影响与建议" />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );
}
