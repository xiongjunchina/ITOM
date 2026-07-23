import { useCallback, useEffect, useMemo, useState } from 'react';
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
  Switch,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import Table from '../../components/SortableTable';
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import { hasPermission, useAuthStore } from '../../stores/auth';
import { currentPeriod, periodLabel, recentPeriods } from '../../utils/period';
import type { PerformanceAssignmentMatrix, PerformanceContributionConfig, PerformanceRoleProfileDefinition } from '../../api/types';
import { useNavigate } from 'react-router-dom';

const periods = recentPeriods(2);
const lineLabels: Record<string, string> = { business: '服务线', professional: '专业线', platform: '平台角色' };
const reviewLabels: Record<string, string> = { manager_review: '负责人初评', cio_direct: 'CIO 直评' };
const contributionLabels: Record<string, string> = {
  special_activity: '专项活动', learning_growth: '学习成长', training_knowledge: '培训知识',
  suggestion_improvement: '建言改进', knowledge_asset: '知识资产', cross_team_support: '跨团队支持',
};

interface RuleFormValues {
  role_code: string;
  name: string;
  line_type: 'business' | 'professional' | 'platform';
  review_mode: 'manager_review' | 'cio_direct';
  description?: string;
  active: boolean;
  dimensions: {
    dimension_code?: string;
    name?: string;
    weight?: number;
    metric?: string;
    evidence_required?: boolean;
    sort?: number;
    active?: boolean;
  }[];
}

/** 绩效规则工作台：展示角色维度权重，并展示周期内员工的总角色权重矩阵。 */
export default function PerformanceRulesWorkbench() {
  const user = useAuthStore((s) => s.user);
  const navigate = useNavigate();
  const canEdit = !!user && (!user.permissions || hasPermission(user, 'performance_admin', 'edit'));
  const [profiles, setProfiles] = useState<PerformanceRoleProfileDefinition[]>([]);
  const [matrix, setMatrix] = useState<PerformanceAssignmentMatrix | null>(null);
  const [period, setPeriod] = useState(currentPeriod());
  const [loading, setLoading] = useState(false);
  const [dialog, setDialog] = useState<{ open: boolean; editing: PerformanceRoleProfileDefinition | null }>({ open: false, editing: null });
  const [saving, setSaving] = useState(false);
  const [contribution, setContribution] = useState<PerformanceContributionConfig | null>(null);
  const [form] = Form.useForm<RuleFormValues>();
  const watchedDimensions = Form.useWatch('dimensions', form) ?? [];

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [profileResult, assignmentResult, contributionResult] = await Promise.all([
        api.getList<PerformanceRoleProfileDefinition>('/admin/performance/role-profiles'),
        api.get<PerformanceAssignmentMatrix>('/admin/performance/assignments', { period }),
        api.get<PerformanceContributionConfig>('/admin/performance/contribution-rules'),
      ]);
      setProfiles(profileResult.items);
      setMatrix(assignmentResult);
      setContribution(contributionResult);
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, [period]);

  const saveContribution = async () => {
    if (!contribution) return;
    const total = Object.values(contribution.weights).reduce((sum, value) => sum + Number(value || 0), 0);
    if (Math.abs(total - 100) > 0.01 || Math.abs(Number(contribution.internal_satisfaction_weight || 0) + Number(contribution.external_satisfaction_weight || 0) - 100) > 0.01) {
      message.error('团队贡献权重及满意度组合比例必须分别合计 100%');
      return;
    }
    await api.put('/admin/performance/contribution-rules', contribution);
    message.success('团队贡献与满意度组合规则已保存');
    void load();
  };

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = () => {
    form.resetFields();
    form.setFieldsValue({
      line_type: 'professional',
      review_mode: 'manager_review',
      active: true,
      dimensions: [{ dimension_code: '', name: '', weight: 100, metric: 'manual', evidence_required: false, sort: 0, active: true }],
    });
    setDialog({ open: true, editing: null });
  };

  const openEdit = (profile: PerformanceRoleProfileDefinition) => {
    form.setFieldsValue({
      role_code: profile.role_code,
      name: profile.name,
      line_type: profile.line_type,
      review_mode: profile.review_mode,
      description: profile.description ?? undefined,
      active: profile.active,
      dimensions: profile.dimensions.map((dimension) => ({
        dimension_code: dimension.dimension_code,
        name: dimension.name,
        weight: dimension.weight,
        metric: dimension.metric,
        evidence_required: dimension.evidence_required,
        sort: dimension.sort,
        active: dimension.active,
      })),
    });
    setDialog({ open: true, editing: profile });
  };

  const closeDialog = () => setDialog({ open: false, editing: null });

  const save = async () => {
    const values = await form.validateFields();
    const dimensions = (values.dimensions ?? []).map((item, index) => ({
      dimension_code: item.dimension_code?.trim() ?? '',
      name: item.name?.trim() ?? '',
      weight: Number(item.weight ?? 0),
      metric: item.metric?.trim() || 'manual',
      evidence_required: item.evidence_required ?? false,
      sort: item.sort ?? index,
      active: item.active ?? true,
    }));
    if (!dimensions.length || Math.abs(dimensions.reduce((sum, item) => sum + item.weight, 0) - 100) > 0.01) {
      message.error('角色内各考核维度权重合计必须为 100%');
      return;
    }
    setSaving(true);
    try {
      let profileId = dialog.editing?.id;
      if (dialog.editing) {
        await api.patch(`/admin/performance/role-profiles/${dialog.editing.id}`, {
          name: values.name,
          line_type: values.line_type,
          review_mode: values.review_mode,
          description: values.description || null,
          active: values.active,
        });
      } else {
        const created = await api.post<{ id: string }>('/admin/performance/role-profiles', {
          role_code: values.role_code,
          name: values.name,
          line_type: values.line_type,
          review_mode: values.review_mode,
          description: values.description || null,
          active: values.active,
        });
        profileId = created.id;
      }
      await api.put(`/admin/performance/role-profiles/${profileId}/dimensions`, { dimensions });
      message.success('绩效角色规则已保存');
      closeDialog();
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const remove = async (profile: PerformanceRoleProfileDefinition) => {
    try {
      // 角色档案当前没有独立删除接口，停用后保留已发布周期快照。
      await api.patch(`/admin/performance/role-profiles/${profile.id}`, { active: false });
      message.success('绩效角色已停用，历史周期仍保留');
      void load();
    } catch {
      // 已统一提示
    }
  };

  const profileColumns: ColumnsType<PerformanceRoleProfileDefinition> = [
    { title: '角色编码', dataIndex: 'role_code', width: 150 },
    { title: '角色名称', dataIndex: 'name', width: 180 },
    { title: '评分条线', dataIndex: 'line_type', width: 110, render: (value: string) => <Tag>{lineLabels[value] ?? value}</Tag> },
    { title: '评分主体', dataIndex: 'review_mode', width: 110, render: (value: string) => reviewLabels[value] ?? value },
    {
      title: '考核维度与权重',
      key: 'dimensions',
      render: (_, profile) => (
        <Space wrap size={[4, 4]}>
          {profile.dimensions.map((dimension) => <Tag key={dimension.id}>{dimension.name} {dimension.weight}%</Tag>)}
        </Space>
      ),
    },
    {
      title: '状态', dataIndex: 'active', width: 80,
      render: (value: boolean) => <Tag color={value ? 'green' : 'default'}>{value ? '启用' : '停用'}</Tag>,
    },
    ...(canEdit ? [{
      title: '操作', key: 'action', width: 140,
      render: (_: unknown, profile: PerformanceRoleProfileDefinition) => (
        <Space size={0}>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(profile)}>编辑</Button>
          {profile.active && <Popconfirm title="停用后只影响新周期，确定继续？" onConfirm={() => void remove(profile)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>停用</Button>
          </Popconfirm>}
        </Space>
      ),
    }] : []),
  ];

  const matrixRows = matrix?.assignments ?? [];
  const employeeRows = useMemo(() => {
    const grouped = new Map<string, {
      person_id: string;
      person_name: string;
      assignments: PerformanceAssignmentMatrix['assignments'];
    }>();
    for (const assignment of matrixRows) {
      const current = grouped.get(assignment.person_id) ?? { person_id: assignment.person_id, person_name: assignment.person_name, assignments: [] };
      current.assignments.push(assignment);
      grouped.set(assignment.person_id, current);
    }
    return [...grouped.values()].map((row) => ({
      ...row,
      role_weight_total: Math.round(row.assignments.reduce((sum, item) => sum + item.role_weight, 0) * 100) / 100,
    }));
  }, [matrixRows]);

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title="角色计分规则"
        extra={<Space>
          {canEdit && <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增角色规则</Button>}
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button>
        </Space>}
      >
        <Alert
          type="info"
          showIcon
          message="总评分矩阵"
          description="每个 IT 员工的常规绩效 = 业务角色贡献（与专业角色合计 80%）+ 团队贡献（固定 20%）。同时承担业务线与专业线角色时，两条线各占 40%；只有一条线角色时，该条线占 80%。平台角色由 CIO 直接评分。"
          style={{ marginBottom: 16 }}
        />
        <Table<PerformanceRoleProfileDefinition>
          rowKey="id"
          loading={loading}
          dataSource={profiles}
          columns={profileColumns}
          standardToolbar={{ exportFileName: '绩效角色规则', searchPlaceholder: '搜索角色、条线或评分主体' }}
          pagination={false}
          expandable={{
            expandedRowRender: (profile) => (
              <Table
                size="small"
                pagination={false}
                rowKey="id"
                dataSource={profile.dimensions}
                columns={[
                  { title: '维度编码', dataIndex: 'dimension_code' },
                  { title: '维度名称', dataIndex: 'name' },
                  { title: '权重', dataIndex: 'weight', render: (value: number) => `${value}%` },
                  { title: '取数指标', dataIndex: 'metric' },
                  { title: '取数方式', dataIndex: 'metric', render: (value: string) => value === 'manual' ? '负责人/CIO评审' : value.startsWith('external') ? '外部原数据' : value === 'internal_external_satisfaction' ? '系统组合（内部+外部）' : '系统自动取数' },
                  { title: '证据要求', dataIndex: 'evidence_required', render: (value: boolean) => value ? '必须' : '可选' },
                ] as ColumnsType<PerformanceRoleProfileDefinition['dimensions'][number]>}
              />
            ),
          }}
          scroll={{ x: 1100 }}
        />
      </Card>

      <Card title="团队贡献与满意度组合规则" extra={canEdit ? <Button type="primary" onClick={() => void saveContribution()}>保存配置</Button> : null}>
        <Alert type="info" showIcon message="团队贡献固定计入常规绩效 20%；本配置只影响当前周期重新取数，已发布周期保留规则快照。" style={{ marginBottom: 12 }} />
        {contribution && <Space direction="vertical" style={{ width: '100%' }}>
          <Space wrap>
            {Object.keys(contributionLabels).map((code) => <Space key={code} align="center"><Typography.Text>{contributionLabels[code]}权重</Typography.Text><InputNumber min={0} max={100} value={contribution.weights[code]} addonAfter="%" disabled={!canEdit} onChange={(value) => setContribution((current) => current ? ({ ...current, weights: { ...current.weights, [code]: Number(value ?? 0) } }) : current)} /></Space>)}
          </Space>
          <Space wrap>
            {Object.keys(contributionLabels).map((code) => <Space key={code} align="center"><Typography.Text>{contributionLabels[code]}目标</Typography.Text><InputNumber min={0.1} value={contribution.targets[code]} addonAfter="分" disabled={!canEdit} onChange={(value) => setContribution((current) => current ? ({ ...current, targets: { ...current.targets, [code]: Number(value ?? 0) } }) : current)} /></Space>)}
          </Space>
          <Space><Typography.Text>内部满意度比例</Typography.Text><InputNumber min={0} max={100} value={contribution.internal_satisfaction_weight} addonAfter="%" disabled={!canEdit} onChange={(value) => setContribution((current) => current ? ({ ...current, internal_satisfaction_weight: Number(value ?? 0) }) : current)} /><Typography.Text>外部满意度比例</Typography.Text><InputNumber min={0} max={100} value={contribution.external_satisfaction_weight} addonAfter="%" disabled={!canEdit} onChange={(value) => setContribution((current) => current ? ({ ...current, external_satisfaction_weight: Number(value ?? 0) }) : current)} /></Space>
        </Space>}
      </Card>

      <Card
        title="周期员工角色权重矩阵"
        extra={<Space>
          <Select value={period} onChange={setPeriod} options={periods.map((value) => ({ value, label: periodLabel(value) }))} />
          {canEdit && <Button onClick={async () => { await api.post(`/admin/performance/${period}/recompute`); message.success('已按当前角色规则重新取数'); void load(); }}>重新取数</Button>}
        </Space>}
      >
        <Alert type="warning" showIcon style={{ marginBottom: 12 }} message={`周期状态：${matrix?.status ?? '加载中'} · 角色权重合计目标为 80%，团队贡献固定 20%`} />
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
          当前周期共 {employeeRows.length} 名 IT 员工；每名员工只占一行，角色分配、权重和评分主体请进入员工详情页集中查看与调整。
        </Typography.Text>
        <Table
          rowKey="person_id"
          loading={loading}
          dataSource={employeeRows}
          columns={[
            { title: '人员', dataIndex: 'person_name', fixed: 'left', width: 130 },
            {
              title: '角色分配', dataIndex: 'assignments', width: 430,
              render: (assignments: PerformanceAssignmentMatrix['assignments']) => <Space wrap size={[4, 4]}>{assignments.map((item) => <Tag key={item.assignment_id}>{item.role_name} · {lineLabels[item.line_type] ?? item.line_type} · {item.role_weight}%</Tag>)}</Space>,
            },
            { title: '角色权重合计', dataIndex: 'role_weight_total', width: 130, render: (value: number) => `${value}%` },
            {
              title: '评分主体', dataIndex: 'assignments', width: 180,
              render: (assignments: PerformanceAssignmentMatrix['assignments']) => <Space wrap size={[4, 4]}>{Array.from(new Set(assignments.map((item) => reviewLabels[item.review_mode] ?? item.review_mode))).map((label) => <Tag key={label}>{label}</Tag>)}</Space>,
            },
            {
              title: '操作', key: 'action', fixed: 'right', width: 130,
              render: (_, row: { person_id: string }) => <Button type="link" onClick={() => navigate(`/team/performance/review/${row.person_id}?period=${encodeURIComponent(period)}&from=rules`)}>{canEdit ? '详情/调整' : '查看详情'}</Button>,
            },
          ] as ColumnsType<{
            person_id: string;
            person_name: string;
            assignments: PerformanceAssignmentMatrix['assignments'];
            role_weight_total: number;
          }>}
          pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: [20, 50, 100] }}
          scroll={{ x: 1000 }}
        />
      </Card>

      <Modal
        title={dialog.editing ? `编辑角色规则：${dialog.editing.name}` : '新增绩效角色规则'}
        open={dialog.open}
        width={820}
        onCancel={closeDialog}
        onOk={() => void save()}
        confirmLoading={saving}
        destroyOnClose
      >
        <Form<RuleFormValues> form={form} layout="vertical" preserve={false}>
          <Space style={{ display: 'flex' }} align="start">
            <Form.Item name="role_code" label="角色编码" rules={[{ required: true }, { pattern: /^[a-z][a-z0-9_]{1,63}$/, message: '使用小写字母、数字和下划线' }]} style={{ flex: 1 }}>
              <Input disabled={!!dialog.editing} />
            </Form.Item>
            <Form.Item name="name" label="角色名称" rules={[{ required: true }]} style={{ flex: 1 }}><Input /></Form.Item>
          </Space>
          <Space style={{ display: 'flex' }} align="start">
            <Form.Item name="line_type" label="评分条线" rules={[{ required: true }]} style={{ flex: 1 }}>
              <Select options={Object.entries(lineLabels).map(([value, label]) => ({ value, label }))} />
            </Form.Item>
            <Form.Item name="review_mode" label="评分主体" rules={[{ required: true }]} style={{ flex: 1 }}>
              <Select options={Object.entries(reviewLabels).map(([value, label]) => ({ value, label }))} />
            </Form.Item>
            <Form.Item name="active" label="启用" valuePropName="checked"><Switch /></Form.Item>
          </Space>
          <Form.Item name="description" label="规则说明"><Input.TextArea rows={2} maxLength={500} /></Form.Item>
          <Form.List name="dimensions">
            {(fields, { add, remove }) => <>
              <Typography.Text strong>角色考核维度（权重合计必须为 100%）</Typography.Text>
              {fields.map((field) => <Space key={field.key} style={{ display: 'flex', marginTop: 8 }} align="start">
                <Form.Item name={[field.name, 'dimension_code']} rules={[{ required: true }]}><Input placeholder="维度编码" style={{ width: 130 }} /></Form.Item>
                <Form.Item name={[field.name, 'name']} rules={[{ required: true }]}><Input placeholder="维度名称" style={{ width: 150 }} /></Form.Item>
                <Form.Item name={[field.name, 'weight']} rules={[{ required: true }]}><InputNumber min={0.1} max={100} placeholder="权重" addonAfter="%" /></Form.Item>
                <Form.Item name={[field.name, 'metric']} rules={[{ required: true }]}><Input placeholder="取数指标/ manual" style={{ width: 180 }} /></Form.Item>
                <Form.Item name={[field.name, 'evidence_required']} valuePropName="checked" label="证据"><Switch size="small" /></Form.Item>
                <Button type="link" danger onClick={() => remove(field.name)}>移除</Button>
              </Space>)}
              <Button type="dashed" block icon={<PlusOutlined />} onClick={() => add({ weight: 0, metric: 'manual', active: true, evidence_required: false })}>增加维度</Button>
              <Typography.Text type={Math.abs(watchedDimensions.reduce((sum, item) => sum + Number(item?.weight ?? 0), 0) - 100) < 0.01 ? 'success' : 'warning'}>
                当前权重合计：{watchedDimensions.reduce((sum, item) => sum + Number(item?.weight ?? 0), 0)}%
              </Typography.Text>
            </>}
          </Form.List>
        </Form>
      </Modal>
    </Space>
  );
}
