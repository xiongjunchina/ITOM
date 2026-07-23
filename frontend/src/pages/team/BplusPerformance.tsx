import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import Table from '../../components/SortableTable';
import { DeleteOutlined, EditOutlined } from '@ant-design/icons';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import { hasPermission, useAuthStore } from '../../stores/auth';
import { currentPeriod, periodLabel, recentPeriods } from '../../utils/period';
import type {
  BplusDimensionScore,
  BplusPersonPerformanceData,
  BplusPerformanceData,
  BplusPerformanceRow,
  BplusRoleScore,
  MyPerformanceData,
  BusinessDomain,
  PerformanceMetricDefinition,
  PerformanceExternalInput,
} from '../../api/types';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

const periods = recentPeriods(2);

function ReviewWorkbench() {
  const user = useAuthStore((s) => s.user);
  const navigate = useNavigate();
  const canAdmin = !!user && (!user.permissions || hasPermission(user, 'performance_admin', 'edit'));
  const [period, setPeriod] = useState(currentPeriod());
  const [data, setData] = useState<BplusPerformanceData | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.get<BplusPerformanceData>('/admin/performance/reviews', { period }));
    } finally {
      setLoading(false);
    }
  }, [period]);

  useEffect(() => {
    void load();
  }, [load]);

  const action = async (name: 'recompute' | 'submit-manager-review' | 'submit-cio-review' | 'publish') => {
    await api.post(`/admin/performance/${period}/${name}`);
    message.success(name === 'publish' ? '绩效结果已发布' : '操作已完成');
    void load();
  };

  const rows = data?.rows ?? [];
  const columns: ColumnsType<BplusPerformanceRow> = [
    { title: '人员', dataIndex: 'person_name', width: 130, fixed: 'left' },
    {
      title: '角色与权重', dataIndex: 'roles', width: 360,
      render: (roles: BplusRoleScore[], row: BplusPerformanceRow) => roles.length ? (
        <Space wrap size={[4, 4]}>
          {roles.map((role) => <Tag key={role.assignment_id}>{role.role_name} · {role.role_weight}%</Tag>)}
        </Space>
      ) : <Tag>{row.role_status ?? '未配置角色'}</Tag>,
    },
    {
      title: '角色贡献', key: 'role_contribution', width: 180,
      render: (_, row) => <Space direction="vertical" size={0}><span>业务：{row.business_contribution.toFixed(1)}</span><span>专业：{row.professional_contribution.toFixed(1)}</span></Space>,
    },
    { title: '团队贡献（20%）', dataIndex: 'team_contribution_score', width: 150, render: (value: number) => `${value.toFixed(1)} × 20% = ${(value * 0.2).toFixed(1)}` },
    { title: '常规绩效', dataIndex: 'regular_score', width: 110, render: (value: number) => value.toFixed(1) },
    { title: '加分 / 扣分', key: 'adjustments', width: 110, render: (_, row) => `${row.bonus.toFixed(1)} / ${row.penalty.toFixed(1)}` },
    { title: '当前总分', dataIndex: 'published_score', width: 110, render: (value: number, row) => row.roles.length ? value.toFixed(1) : '—' },
    {
      title: '操作', key: 'action', fixed: 'right', width: 110,
      render: (_, row) => <Button type="link" onClick={() => navigate(`/team/performance/review/${row.person_id}?period=${encodeURIComponent(period)}`)}>评分明细</Button>,
    },
  ];

  return (
    <Card
      title="分级评审工作台"
      extra={
        <Space>
          <Select value={period} onChange={setPeriod} options={periods.map((value) => ({ value, label: periodLabel(value) }))} />
          {canAdmin && <Button onClick={() => void action('recompute')}>重新取数</Button>}
          {canAdmin && <Button onClick={() => void action('submit-cio-review')}>提交 CIO 终审</Button>}
          {canAdmin && <Button type="primary" onClick={() => void action('publish')}>发布结果</Button>}
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message={`周期状态：${data?.status ?? '加载中'} · 系统参考分、负责人初评和 CIO 终审分开保存`}
      />
      <Table
        rowKey="person_id"
        loading={loading}
        dataSource={rows}
        columns={columns}
        standardToolbar={{ exportFileName: '周期员工绩效汇总', searchPlaceholder: '搜索员工、角色或条线' }}
        scroll={{ x: 1300 }}
        pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: [20, 50, 100] }}
      />
    </Card>
  );
}

const lineLabels: Record<string, string> = { business: '业务线', professional: '专业线', platform: '平台角色' };
const reviewModeLabels: Record<string, string> = { manager_review: '负责人初评', cio_direct: 'CIO 直评' };

/** 单个员工的评审详情：展开该员工全部角色、维度、权重及多级评分。 */
export function ReviewDetailPage() {
  const { personId } = useParams<{ personId: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const user = useAuthStore((s) => s.user);
  const canAdmin = !!user && (!user.permissions || hasPermission(user, 'performance_admin', 'edit'));
  const canReview = !!user && (!user.permissions || hasPermission(user, 'performance_review', 'edit'));
  const [period, setPeriod] = useState(searchParams.get('period') || currentPeriod());
  const [data, setData] = useState<BplusPersonPerformanceData | null>(null);
  const [loading, setLoading] = useState(false);
  const [roleWeights, setRoleWeights] = useState<Record<string, number>>({});
  const [evaluatorWeights, setEvaluatorWeights] = useState<Record<string, Record<string, number>>>({});
  const [editing, setEditing] = useState<{ assignment: BplusRoleScore; dimension: BplusDimensionScore } | null>(null);
  const [score, setScore] = useState<number | null>(null);
  const [reason, setReason] = useState('');

  const load = useCallback(async () => {
    if (!personId) return;
    setLoading(true);
    try {
      const result = await api.get<BplusPersonPerformanceData>(`/admin/performance/reviews/person/${personId}`, { period });
      setData(result);
      setRoleWeights(Object.fromEntries(result.row.roles.map((role) => [role.assignment_id, role.role_weight])));
      setEvaluatorWeights(Object.fromEntries(result.row.roles.map((role) => [role.assignment_id, role.evaluator_weights ?? {}])));
    } finally {
      setLoading(false);
    }
  }, [personId, period]);

  useEffect(() => {
    void load();
  }, [load]);

  const changePeriod = (value: string) => {
    setPeriod(value);
    setSearchParams({ period: value }, { replace: true });
  };

  const locked = data?.status === 'published' || data?.status === 'locked';
  const roles = data?.row.roles ?? [];
  const roleWeightTotal = roles.reduce((sum, role) => sum + Number(roleWeights[role.assignment_id] ?? role.role_weight), 0);

  const saveWeights = async () => {
    if (!data) return;
    if (Math.abs(roleWeightTotal - 80) > 0.01) {
      message.error('角色权重合计必须为 80%');
      return;
    }
    await api.put('/admin/performance/assignments', {
      period,
      person_id: data.row.person_id,
      assignments: roles.map((role) => ({
        assignment_id: role.assignment_id,
        role_weight: Number(roleWeights[role.assignment_id] ?? role.role_weight),
        evaluator_ids: role.evaluator_ids,
        evaluator_weights: evaluatorWeights[role.assignment_id] ?? role.evaluator_weights,
      })),
    });
    message.success('角色权重已保存');
    void load();
  };

  const openScoreEditor = (assignment: BplusRoleScore, dimension: BplusDimensionScore) => {
    setEditing({ assignment, dimension });
    setScore(dimension.effective_score);
    setReason(dimension.reason ?? '');
  };

  const saveScore = async () => {
    if (!editing) return;
    if (!reason.trim()) {
      message.error('请填写评分或修正说明');
      return;
    }
    await api.put(`/admin/performance/reviews/${editing.assignment.assignment_id}/components/${editing.dimension.code}`, { score, reason });
    message.success('评分已保存');
    setEditing(null);
    void load();
  };

  if (!personId) return <Alert type="error" message="缺少员工标识" />;
  if (!data?.row && !loading) return <Alert type="warning" message="当前考核周期没有该员工的评审记录" />;

  const row = data?.row;
  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title={row ? `${row.person_name} · 评审详情` : '评审详情'}
        extra={<Space>
          <Select value={period} onChange={changePeriod} options={periods.map((value) => ({ value, label: periodLabel(value) }))} />
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>返回评审总览</Button>
        </Space>}
        loading={loading}
      >
        {row && <>
          <Alert type="info" showIcon style={{ marginBottom: 16 }} message={`周期状态：${data?.status ?? '加载中'} · 系统参考、负责人初评、CIO 终审和生效分分别保留`} />
          <Space wrap size={[8, 8]}>
            <Tag>业务角色贡献：{row.business_contribution.toFixed(1)}</Tag>
            <Tag>专业角色贡献：{row.professional_contribution.toFixed(1)}</Tag>
            <Tag>团队贡献：{row.team_contribution_score.toFixed(1)} × 20%</Tag>
            <Tag color="blue">常规绩效：{row.regular_score.toFixed(1)}</Tag>
            <Tag color="green">当前总分：{row.published_score.toFixed(1)}</Tag>
          </Space>
        </>}
      </Card>

      {row?.roles.map((role) => {
        const weight = Number(roleWeights[role.assignment_id] ?? role.role_weight);
        return (
          <Card
            key={role.assignment_id}
            type="inner"
            title={<Space><Typography.Text strong>{role.role_name}</Typography.Text><Tag>{lineLabels[role.line_type] ?? role.line_type}</Tag><Tag>{reviewModeLabels[role.review_mode] ?? role.review_mode}</Tag></Space>}
            extra={<Space>
              {canAdmin && !locked ? <InputNumber min={0} max={100} step={1} addonAfter="%" value={weight} onChange={(value) => setRoleWeights((current) => ({ ...current, [role.assignment_id]: value ?? 0 }))} /> : <Typography.Text>权重 {weight}%</Typography.Text>}
              {canAdmin && !locked && <Button type="link" onClick={() => void saveWeights()}>保存权重</Button>}
            </Space>}
          >
            <Typography.Text type={Math.abs(roleWeightTotal - 80) <= 0.01 ? 'secondary' : 'warning'}>当前员工角色权重合计：{roleWeightTotal.toFixed(1)}%（目标 80%） · 角色分：{role.role_score ?? '待评分'}</Typography.Text>
            {role.evaluator_ids.length > 0 && <Space wrap style={{ margin: '8px 0' }}><Typography.Text>评审人权重：</Typography.Text>{role.evaluator_ids.map((evaluatorId) => <Space key={evaluatorId}><Typography.Text code>{evaluatorId}</Typography.Text><InputNumber min={0.1} max={100} value={evaluatorWeights[role.assignment_id]?.[evaluatorId] ?? role.evaluator_weights?.[evaluatorId]} addonAfter="%" disabled={!canAdmin || locked} onChange={(value) => setEvaluatorWeights((current) => ({ ...current, [role.assignment_id]: { ...(current[role.assignment_id] ?? role.evaluator_weights ?? {}), [evaluatorId]: Number(value ?? 0) } }))} /></Space>)}</Space>}
            <Table<BplusDimensionScore>
              rowKey="code"
              size="small"
              loading={loading}
              dataSource={role.dimensions}
              pagination={false}
              scroll={{ x: 1100 }}
              columns={[
                { title: '评价维度', dataIndex: 'name', width: 190 },
                { title: '维度权重', dataIndex: 'weight', width: 100, render: (value: number) => `${value}%` },
                { title: '系统参考', dataIndex: 'system_score', width: 110, render: (value: number | null) => value ?? '—' },
                { title: '业务负责人初评', dataIndex: 'business_manager_score', width: 130, render: (value: number | null) => value ?? '—' },
                { title: '专业负责人初评', dataIndex: 'professional_manager_score', width: 130, render: (value: number | null) => value ?? '—' },
                { title: '评审人独立评分', dataIndex: 'manager_scores', width: 220, render: (value: Record<string, number>) => value && Object.keys(value).length ? Object.entries(value).map(([id, item]) => `${id}: ${item}`).join('；') : '—' },
                { title: 'CIO 终审/微调', dataIndex: 'cio_score', width: 120, render: (value: number | null) => value ?? '—' },
                { title: '当前生效分', dataIndex: 'effective_score', width: 110, render: (value: number | null) => value ?? '待评分' },
                { title: '修正说明', dataIndex: 'reason', width: 260, ellipsis: true, render: (value: string | null) => value || '—' },
                {
                  title: '操作', key: 'action', fixed: 'right', width: 90,
                  render: (_, dimension) => canReview && !locked ? <Button type="link" onClick={() => openScoreEditor(role, dimension)}>调整</Button> : <Typography.Text type="secondary">只读</Typography.Text>,
                },
              ]}
            />
          </Card>
        );
      })}

      <Modal
        open={editing != null}
        title={editing ? `调整 ${row?.person_name ?? ''} · ${editing.assignment.role_name} · ${editing.dimension.name}` : undefined}
        onCancel={() => setEditing(null)}
        onOk={() => void saveScore()}
        okText="保存评分"
      >
        <Typography.Paragraph type="secondary">评分范围 0–100；允许清除当前评分，但必须填写本次评分或修正的理由。</Typography.Paragraph>
        <InputNumber min={0} max={100} value={score} onChange={setScore} placeholder="评分（可留空以清除）" style={{ width: '100%', marginBottom: 12 }} />
        <Input.TextArea value={reason} onChange={(event) => setReason(event.target.value)} rows={4} placeholder="请填写评分依据、上级微调原因或修正说明" />
      </Modal>
    </Space>
  );
}

function ExternalInputWorkbench() {
  const user = useAuthStore((state) => state.user);
  const canExternalEdit = !!user && hasPermission(user, 'performance_external', 'edit');
  const canExternalDelete = !!user && hasPermission(user, 'performance_external', 'delete');
  const [period, setPeriod] = useState(currentPeriod());
  const [items, setItems] = useState<PerformanceExternalInput[]>([]);
  const [metricDefinitions, setMetricDefinitions] = useState<PerformanceMetricDefinition[]>([]);
  const [domains, setDomains] = useState<BusinessDomain[]>([]);
  const [editing, setEditing] = useState<PerformanceExternalInput | null>(null);
  const [form] = Form.useForm();
  const targetType = Form.useWatch('target_type', form) ?? 'business_domain';
  const metricCode = Form.useWatch('metric_code', form) ?? 'external_business_satisfaction';

  const load = useCallback(async () => {
    try {
      setItems(await api.get<PerformanceExternalInput[]>('/admin/performance/external-inputs', { period }));
    } catch {
      // 已统一提示
    }
    try {
      setMetricDefinitions(await api.get<PerformanceMetricDefinition[]>('/admin/performance/metric-definitions'));
    } catch {
      // 已统一提示
    }
    try {
      const result = await api.getList<BusinessDomain>('/admin/business-domains');
      setDomains(result.items.filter((domain) => domain.active));
    } catch {
      // 已统一提示
    }
  }, [period]);

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ metric_code: 'external_business_satisfaction', target_type: 'business_domain', raw_scale: 100 });
  };

  const openEdit = (item: PerformanceExternalInput) => {
    if (item.status === 'locked') return;
    setEditing(item);
    form.setFieldsValue({
      metric_code: item.metric_code,
      target_type: item.target_type,
      target_id: item.target_id,
      evaluator_name: item.evaluator_name,
      evaluator_department: item.evaluator_department ?? undefined,
      raw_score: item.raw_score,
      raw_scale: item.raw_scale,
      comment: item.comment ?? undefined,
    });
  };

  const remove = async (item: PerformanceExternalInput) => {
    if (item.status === 'locked') return;
    await api.delete(`/admin/performance/external-inputs/${item.id}`);
    message.success('外部原数据已删除');
    if (editing?.id === item.id) {
      setEditing(null);
      form.resetFields();
      form.setFieldsValue({ metric_code: 'external_business_satisfaction', target_type: 'business_domain', raw_scale: 100 });
    }
    void load();
  };

  return (
    <Card title="外部评价与原数据" extra={<Select value={period} onChange={(value) => { setPeriod(value); openCreate(); }} options={periods.map((value) => ({ value, label: periodLabel(value) }))} />}>
      <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="这里录入系统外业务负责人评分，不直接覆盖评分结果；锁定后只能通过新版本修订。" />
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="外部业务满意度按百分比计分"
        description="建议直接按百分制录入 0–100（例如 86 表示 86%）。系统统一按原始分 ÷ 满分 × 100 折算为百分比；例如供应链服务域外部评分 86/100、内部 ITSM 满意度 92% 时，内外部满意度 = (86% + 92%) ÷ 2 = 89%，再按该角色维度权重计入绩效。"
      />
      <Card type="inner" title="当前绩效指标定义" style={{ marginBottom: 16 }}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
          下面的清单来自当前启用的角色规则。系统自动取数的指标只读展示；标记为“外部原数据”或“人工评审”的指标，说明系统无法直接获得，需要录入原始事实或在分级评审中填写。
        </Typography.Paragraph>
        <Table<PerformanceMetricDefinition>
          rowKey="metric_code"
          size="small"
          pagination={false}
          dataSource={metricDefinitions}
          columns={[
            { title: '指标编码', dataIndex: 'metric_code', width: 190 },
            { title: '指标名称', dataIndex: 'name', width: 150 },
            {
              title: '来源', dataIndex: 'source_type', width: 120,
              render: (value: string) => <Tag color={value === 'external' ? 'orange' : value === 'system' ? 'blue' : value === 'derived' ? 'purple' : 'default'}>{value === 'external' ? '外部原数据' : value === 'system' ? '系统自动取数' : value === 'derived' ? '复合计算' : '人工评审'}</Tag>,
            },
            { title: '取数方式', dataIndex: 'collection_mode', width: 120, render: (value: string) => value === 'external_input' ? '本页录入' : value === 'auto' ? '系统计算' : value === 'derived' ? '系统组合' : '评审填写' },
            { title: '口径说明', dataIndex: 'description', width: 380 },
            {
              title: '使用角色/维度', dataIndex: 'references', width: 300,
              render: (references: PerformanceMetricDefinition['references']) => <Space wrap size={[4, 4]}>{references.map((ref) => <Tag key={`${ref.role_code}-${ref.dimension_code}`}>{ref.role_name} · {ref.dimension_name} {ref.weight}%</Tag>)}</Space>,
            },
          ] as ColumnsType<PerformanceMetricDefinition>}
          scroll={{ x: 1250 }}
        />
      </Card>
      <Form
        form={form}
        layout="inline"
        initialValues={{ metric_code: 'external_business_satisfaction', target_type: 'business_domain', raw_scale: 100 }}
        onFinish={async (values) => {
          if (editing) {
            await api.patch(`/admin/performance/external-inputs/${editing.id}`, { ...values, period, status: editing.status });
            message.success('外部原数据已更新');
          } else {
            await api.post('/admin/performance/external-inputs', { ...values, period, status: 'verified' });
            message.success('外部原数据已录入');
          }
          setEditing(null);
          form.resetFields();
          form.setFieldsValue({ metric_code: 'external_business_satisfaction', target_type: 'business_domain', raw_scale: 100 });
          void load();
        }}
        style={{ marginBottom: 16 }}
      >
        <Form.Item name="metric_code"><Select showSearch optionFilterProp="label" placeholder="选择指标" options={metricDefinitions.filter((metric) => metric.collection_mode === 'external_input').map((metric) => ({ value: metric.metric_code, label: `${metric.name}（${metric.metric_code}）` }))} /></Form.Item>
        <Form.Item name="target_type"><Select options={[{ value: 'business_domain', label: '业务服务域' }]} /></Form.Item>
        <Form.Item name="target_id" rules={[{ required: true, message: '请选择业务服务域' }]}>
          {targetType === 'business_domain' ? <Select showSearch optionFilterProp="label" placeholder="选择被评价业务服务域" options={domains.map((domain) => ({ value: domain.id, label: `${domain.name}（${domain.code}）` }))} /> : <Input placeholder="目标 ID" />}
        </Form.Item>
        <Form.Item name="evaluator_name" rules={[{ required: true, message: '请输入评价人' }]}><Input placeholder="评价人" /></Form.Item>
        <Form.Item name="evaluator_department"><Input placeholder="评价部门" /></Form.Item>
        <Form.Item
          name="raw_score"
          label={metricCode === 'external_business_satisfaction' ? <Tooltip title="取值范围为 0–满分；外部业务满意度建议使用 0–100 百分制。">原始分（百分比）</Tooltip> : '原始分'}
          rules={[{ required: true, message: '请输入原始分' }]}
          extra={metricCode === 'external_business_satisfaction' ? '建议输入 0–100，例如 86 表示 86%。' : undefined}
        >
          <InputNumber min={0} max={metricCode === 'external_business_satisfaction' ? 100 : undefined} placeholder="原始分" />
        </Form.Item>
        <Form.Item name="raw_scale" initialValue={100} label="满分"><InputNumber min={0.1} placeholder="满分" /></Form.Item>
        <Form.Item name="comment"><Input placeholder="评价说明" /></Form.Item>
        {editing && <Button onClick={openCreate}>取消编辑</Button>}
        <Button type="primary" htmlType="submit">{editing ? '保存修改' : '录入'}</Button>
      </Form>
      <Table
        rowKey="id"
        dataSource={items}
        columns={[
          { title: '指标', dataIndex: 'metric_code' },
          { title: '评价业务域', render: (_, row) => row.target_name || row.target_id },
          { title: '评价人', dataIndex: 'evaluator_name' },
          { title: '原始分', render: (_, row) => `${row.raw_score}/${row.raw_scale}` },
          { title: '折算分（百分比）', dataIndex: 'normalized_score', render: (value: number | null) => value == null ? '—' : `${value}%` },
          { title: '状态', dataIndex: 'status' },
          { title: '说明', dataIndex: 'comment' },
          {
            title: '操作', key: 'actions', width: 150, fixed: 'right',
            render: (_, row) => row.status === 'locked' ? <Tag>已锁定</Tag> : (
              <Space size={4}>
                {canExternalEdit && <Button type="link" icon={<EditOutlined />} onClick={() => openEdit(row)}>编辑</Button>}
                {canExternalDelete && <Popconfirm title="确认删除这条外部原数据吗？" onConfirm={() => void remove(row)}>
                  <Button type="link" danger icon={<DeleteOutlined />}>删除</Button>
                </Popconfirm>}
              </Space>
            ),
          },
        ] as ColumnsType<PerformanceExternalInput>}
        scroll={{ x: 1350 }}
      />
    </Card>
  );
}

function MyPerformanceResult() {
  const [period, setPeriod] = useState(currentPeriod());
  const [data, setData] = useState<MyPerformanceData | null>(null);

  useEffect(() => {
    void api.get<MyPerformanceData>('/my/performance', { period }).then(setData);
  }, [period]);

  return (
    <Card title="我的最终绩效结果" extra={<Select value={period} onChange={setPeriod} options={periods.map((value) => ({ value, label: periodLabel(value) }))} />}>
      {!data?.published || !data.result ? (
        <Alert type="info" showIcon message="本周期结果尚未发布" />
      ) : (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Typography.Title level={3} style={{ margin: 0 }}>最终展示分：{data.result.published_score}</Typography.Title>
          <Space wrap>
            <Tag>业务角色贡献：{data.result.business_role_score ?? '—'}</Tag>
            <Tag>专业角色贡献：{data.result.professional_role_score ?? '—'}</Tag>
            <Tag>团队贡献：{data.result.team_contribution_score}</Tag>
            <Tag color="green">常规绩效：{data.result.regular_score}</Tag>
          </Space>
          <Table
            rowKey="role_code"
            pagination={false}
            dataSource={data.result.roles}
            columns={[
              { title: '角色', dataIndex: 'role_name' },
              { title: '权重', dataIndex: 'role_weight', render: (value: number) => `${value}%` },
              { title: '角色得分', dataIndex: 'role_score', render: (value: number | null) => value ?? '—' },
            ]}
          />
        </Space>
      )}
    </Card>
  );
}

export { ReviewWorkbench, ExternalInputWorkbench, MyPerformanceResult };
