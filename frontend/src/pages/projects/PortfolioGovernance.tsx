import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
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
  Skeleton,
  Space,
  Statistic,
  Switch,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ArrowLeftOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import dayjs, { type Dayjs } from 'dayjs';
import { api } from '../../api/client';
import type {
  Member,
  PortfolioDashboard,
  PortfolioGovernanceActionRow,
  PortfolioGovernedProject,
  PortfolioObjective,
  PortfolioScoringRule,
  ProjectDependencyRow,
  ProjectRow,
  ResourceCommitmentRow,
  ResourceConflictRow,
} from '../../api/types';
import Table from '../../components/SortableTable';
import { useT } from '../../i18n';
import { hasPermission, useAuthStore } from '../../stores/auth';
import { HealthDot } from './shared';

type GovernanceStatus = PortfolioGovernedProject['governance_status'];

const TRANSITIONS: Record<string, string[]> = {
  candidate: ['scoring', 'rejected'],
  scoring: ['pending_review', 'deferred', 'rejected'],
  pending_review: ['admitted', 'deferred', 'rejected'],
  admitted: ['paused', 'completed', 'terminated'],
  paused: ['admitted', 'terminated'],
  deferred: ['scoring', 'rejected'],
  rejected: ['candidate'],
};

const statusColor: Record<string, string> = {
  candidate: 'default',
  scoring: 'processing',
  pending_review: 'gold',
  admitted: 'green',
  deferred: 'orange',
  paused: 'orange',
  completed: 'blue',
  terminated: 'red',
  rejected: 'red',
};

function pct(value: number | null | undefined) {
  return value == null ? '-' : `${value}%`;
}

export default function PortfolioGovernance() {
  const { id } = useParams();
  const navigate = useNavigate();
  const t = useT();
  const user = useAuthStore((state) => state.user);
  const canSubmitGovernance = !!user && (hasPermission(user, 'portfolio_governance', 'create') || hasPermission(user, 'portfolio_governance', 'edit'));
  const canEditGovernance = !!user && hasPermission(user, 'portfolio_governance', 'edit');
  const canScore = !!user && hasPermission(user, 'portfolio_scoring', 'edit');
  const canConfigureRules = canScore && canEditGovernance;
  const canDecide = !!user && hasPermission(user, 'portfolio_decision', 'edit');
  const canResource = !!user && hasPermission(user, 'portfolio_resource', 'edit');
  const canDeleteResource = !!user && hasPermission(user, 'portfolio_resource', 'delete');
  const canAudit = !!user && hasPermission(user, 'portfolio_audit', 'view');

  const [data, setData] = useState<PortfolioDashboard | null>(null);
  const [auditRows, setAuditRows] = useState<PortfolioGovernanceActionRow[]>([]);
  const [projectRefs, setProjectRefs] = useState<ProjectRow[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [objectiveOpen, setObjectiveOpen] = useState(false);
  const [editingObjective, setEditingObjective] = useState<PortfolioObjective | null>(null);
  const [editingRule, setEditingRule] = useState<PortfolioScoringRule | null>(null);
  const [scoreProject, setScoreProject] = useState<PortfolioGovernedProject | null>(null);
  const [contributionProject, setContributionProject] = useState<PortfolioGovernedProject | null>(null);
  const [transitionProject, setTransitionProject] = useState<PortfolioGovernedProject | null>(null);
  const [dependencyOpen, setDependencyOpen] = useState(false);
  const [resourceOpen, setResourceOpen] = useState(false);
  const [baselineOpen, setBaselineOpen] = useState(false);

  const [objectiveForm] = Form.useForm();
  const [scoreForm] = Form.useForm();
  const [contributionForm] = Form.useForm();
  const [transitionForm] = Form.useForm();
  const [dependencyForm] = Form.useForm();
  const [resourceForm] = Form.useForm();
  const [baselineForm] = Form.useForm();
  const [ruleForm] = Form.useForm();

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const dashboard = await api.get<PortfolioDashboard>(`/portfolios/${id}/dashboard`);
      setData(dashboard);
      const [projects, people] = await Promise.all([
        api.getList<ProjectRow>('/projects', { page: 1, page_size: 500 }),
        api.getList<Member>('/members', { page: 1, page_size: 2000, scope: 'it' }),
      ]);
      setProjectRefs(projects.items);
      setMembers(people.items);
      if (canAudit) {
        const actions = await api.getList<PortfolioGovernanceActionRow>(`/portfolios/${id}/governance-actions`);
        setAuditRows(actions.items);
      }
    } finally {
      setLoading(false);
    }
  }, [canAudit, id]);

  useEffect(() => {
    void load();
  }, [load]);

  const withSave = async (work: () => Promise<unknown>) => {
    setSaving(true);
    try {
      await work();
      message.success(t('portfolio.saved'));
      await load();
      return true;
    } finally {
      setSaving(false);
    }
  };

  const openScore = (project: PortfolioGovernedProject) => {
    setScoreProject(project);
    const values: Record<string, unknown> = {};
    for (const rule of data?.scoring_rules ?? []) {
      values[`score_${rule.id}`] = project.scores[rule.dimension_code];
      values[`evidence_${rule.id}`] = project.score_details[rule.dimension_code]?.evidence;
    }
    scoreForm.setFieldsValue(values);
  };

  const openContributions = (project: PortfolioGovernedProject) => {
    setContributionProject(project);
    contributionForm.setFieldsValue({ contributions: project.objective_contributions });
  };

  const openObjective = (objective?: PortfolioObjective) => {
    setEditingObjective(objective ?? null);
    setObjectiveOpen(true);
    objectiveForm.resetFields();
    objectiveForm.setFieldsValue(objective ? {
      ...objective,
      period: objective.period_start && objective.period_end
        ? [dayjs(objective.period_start), dayjs(objective.period_end)]
        : undefined,
    } : { weight: 0, status: 'active' });
  };

  const openRule = (rule: PortfolioScoringRule) => {
    setEditingRule(rule);
    ruleForm.setFieldsValue(rule);
  };

  const projectOptions = useMemo(
    () => projectRefs.map((project) => ({ value: project.id, label: `${project.project_code} ${project.name}` })),
    [projectRefs],
  );

  if (loading && !data) {
    return <Card><Skeleton active paragraph={{ rows: 10 }} /></Card>;
  }
  if (!data) {
    return <Card><Empty description={t('portfolio.notFound')}><Button onClick={() => navigate('/projects/portfolios')}>{t('portfolio.back')}</Button></Empty></Card>;
  }

  const projectColumns: ColumnsType<PortfolioGovernedProject> = [
    {
      title: t('portfolio.project'),
      dataIndex: 'name',
      width: 230,
      render: (value: string, row) => <Link to={`/projects/${row.project_id}`}>{row.project_code} · {value}</Link>,
    },
    { title: t('portfolio.pm'), dataIndex: 'pm_name', width: 110, render: (value) => value || '-' },
    {
      title: t('portfolio.governanceStatus'), dataIndex: 'governance_status', width: 130,
      render: (value: GovernanceStatus) => <Tag color={statusColor[value]}>{t(`portfolio.status.${value}`)}</Tag>,
    },
    { title: t('portfolio.systemScore'), dataIndex: 'system_score', width: 100, align: 'right', render: (value) => value ?? t('portfolio.pendingScore') },
    { title: t('portfolio.priority'), dataIndex: 'priority_rank', width: 80, align: 'center', render: (value) => value ?? '-' },
    {
      title: t('portfolio.health'), dataIndex: 'health', width: 100,
      render: (value) => <Space size={6}><HealthDot health={value} />{t(`portfolio.health.${value}`)}</Space>,
    },
    { title: t('portfolio.progress'), dataIndex: 'progress', width: 130, render: (value) => <Progress percent={value ?? 0} size="small" format={() => pct(value)} /> },
    { title: t('portfolio.budget'), dataIndex: 'budget_10k', width: 110, align: 'right', render: (value) => value == null ? '-' : `${value.toFixed(1)}` },
    {
      title: t('common.actions'), key: 'actions', width: 260, fixed: 'right',
      render: (_value, row) => (
        <Space size={0} wrap>
          {canScore && <Button type="link" size="small" onClick={() => openScore(row)}>{t('portfolio.score')}</Button>}
          {canSubmitGovernance && <Button type="link" size="small" onClick={() => openContributions(row)}>{t('portfolio.contribution')}</Button>}
          {canDecide && (TRANSITIONS[row.governance_status] ?? []).length > 0 && (
            <Button type="link" size="small" onClick={() => { setTransitionProject(row); transitionForm.resetFields(); }}>{t('portfolio.decision')}</Button>
          )}
        </Space>
      ),
    },
  ];

  const objectiveColumns: ColumnsType<PortfolioObjective> = [
    { title: t('portfolio.objectiveCode'), dataIndex: 'objective_code', width: 120 },
    { title: t('portfolio.objective'), dataIndex: 'name', width: 220 },
    { title: t('portfolio.metric'), dataIndex: 'metric_name', width: 150, render: (value) => value || '-' },
    { title: t('portfolio.target'), dataIndex: 'target_value', width: 100, align: 'right', render: (value) => value ?? '-' },
    { title: t('portfolio.current'), dataIndex: 'current_value', width: 100, align: 'right', render: (value) => value ?? '-' },
    { title: t('portfolio.weight'), dataIndex: 'weight', width: 90, align: 'right', render: (value) => `${value}%` },
    { title: t('portfolio.owner'), dataIndex: 'owner_name', width: 120, render: (value) => value || '-' },
    { title: t('common.status'), dataIndex: 'status', width: 100, render: (value) => <Tag>{t(`portfolio.objectiveStatus.${value}`)}</Tag> },
    {
      title: t('common.actions'), key: 'actions', width: 90,
      render: (_value, row) => canEditGovernance
        ? <Button type="link" size="small" onClick={() => openObjective(row)}>{t('common.edit')}</Button>
        : null,
    },
  ];

  const scoringRuleColumns: ColumnsType<PortfolioScoringRule> = [
    { title: t('portfolio.ruleCode'), dataIndex: 'dimension_code', width: 180 },
    { title: t('portfolio.ruleName'), dataIndex: 'name', width: 180 },
    { title: t('portfolio.weight'), dataIndex: 'weight', width: 90, align: 'right', render: (value) => `${value}%` },
    { title: t('portfolio.evidenceRequired'), dataIndex: 'evidence_required', width: 120, render: (value) => value ? t('proj.yes') : t('proj.no') },
    { title: t('portfolio.active'), dataIndex: 'active', width: 90, render: (value) => <Tag color={value ? 'green' : 'default'}>{value ? t('proj.yes') : t('proj.no')}</Tag> },
    {
      title: t('common.actions'), key: 'actions', width: 90,
      render: (_value, row) => canConfigureRules
        ? <Button type="link" size="small" onClick={() => openRule(row)}>{t('common.edit')}</Button>
        : null,
    },
  ];

  const dependencyColumns: ColumnsType<ProjectDependencyRow> = [
    { title: t('portfolio.predecessor'), dataIndex: 'predecessor_project_name', width: 180, render: (value) => value || '-' },
    { title: t('portfolio.successor'), dataIndex: 'successor_project_name', width: 180, render: (value) => value || '-' },
    { title: t('portfolio.deliverable'), dataIndex: 'deliverable', width: 200 },
    { title: t('portfolio.dependencyType'), dataIndex: 'dependency_type', width: 150, render: (value) => t(`portfolio.dependency.${value}`) },
    { title: t('portfolio.dueDate'), dataIndex: 'due_date', width: 110, render: (value) => value || '-' },
    { title: t('portfolio.impact'), dataIndex: 'impact', width: 90, render: (value) => <Tag color={value === 'high' ? 'red' : value === 'medium' ? 'gold' : 'default'}>{t(`portfolio.impact.${value}`)}</Tag> },
    { title: t('common.status'), dataIndex: 'status', width: 100, render: (value) => <Tag>{t(`portfolio.dependencyStatus.${value}`)}</Tag> },
  ];

  const commitmentColumns: ColumnsType<ResourceCommitmentRow> = [
    { title: t('portfolio.project'), dataIndex: 'project_name', width: 180 },
    { title: t('portfolio.person'), dataIndex: 'person_name', width: 120 },
    { title: t('portfolio.role'), dataIndex: 'role_name', width: 120, render: (value) => value || '-' },
    { title: t('portfolio.period'), key: 'period', width: 220, render: (_value, row) => `${row.start_date} ~ ${row.end_date}` },
    { title: t('portfolio.allocation'), dataIndex: 'allocation_percent', width: 100, align: 'right', render: (value) => `${value}%` },
    ...(canDeleteResource ? [{
      title: t('common.actions'), key: 'actions', width: 90,
      render: (_value: unknown, row: ResourceCommitmentRow) => (
        <Popconfirm title={t('portfolio.deleteCommitmentConfirm')} onConfirm={() => void withSave(() => api.delete(`/project-resource-commitments/${row.id}`))}>
          <Button type="link" danger size="small">{t('common.delete')}</Button>
        </Popconfirm>
      ),
    } as ColumnsType<ResourceCommitmentRow>[number]] : []),
  ];

  const conflictColumns: ColumnsType<ResourceConflictRow> = [
    { title: t('portfolio.person'), dataIndex: 'person_name', width: 130 },
    { title: t('portfolio.conflictPeriod'), key: 'period', width: 220, render: (_value, row) => `${row.start_date} ~ ${row.end_date}` },
    { title: t('portfolio.totalAllocation'), dataIndex: 'allocation_percent', width: 120, render: (value) => <Tag color="red">{value}%</Tag> },
    { title: t('portfolio.involvedProjects'), dataIndex: 'commitments', render: (rows: ResourceConflictRow['commitments']) => rows.map((row) => `${row.project_name ?? row.project_id} ${row.allocation_percent}%`).join('；') },
  ];

  const auditColumns: ColumnsType<PortfolioGovernanceActionRow> = [
    { title: t('portfolio.action'), dataIndex: 'action', width: 170, render: (value) => t(`portfolio.action.${value}`) },
    { title: t('portfolio.reason'), dataIndex: 'reason', ellipsis: true },
    { title: t('portfolio.actor'), dataIndex: 'actor_id', width: 180 },
    { title: t('portfolio.effectiveAt'), dataIndex: 'effective_at', width: 180, render: (value) => value?.replace('T', ' ').slice(0, 19) },
  ];

  const tabs = [
    {
      key: 'projects',
      label: t('portfolio.tab.projects'),
      children: data.projects.length ? <Table rowKey="membership_id" columns={projectColumns} dataSource={data.projects} pagination={false} scroll={{ x: 1250 }} /> : <Empty description={t('portfolio.noProjects')} />,
    },
    {
      key: 'objectives',
      label: t('portfolio.tab.objectives'),
      children: <Space direction="vertical" style={{ width: '100%' }} size={12}>
        {canEditGovernance && <Button type="primary" icon={<PlusOutlined />} onClick={() => openObjective()}>{t('portfolio.newObjective')}</Button>}
        {data.objectives.length ? <Table rowKey="id" columns={objectiveColumns} dataSource={data.objectives} pagination={false} scroll={{ x: 1090 }} /> : <Empty description={t('portfolio.noObjectives')} />}
        <Card size="small" title={t('portfolio.scoringRules')} extra={<Typography.Text type="secondary">{t('portfolio.scoringRuleHint')}</Typography.Text>}>
          <Table rowKey="id" columns={scoringRuleColumns} dataSource={data.scoring_rules} pagination={false} scroll={{ x: 750 }} />
        </Card>
      </Space>,
    },
    {
      key: 'dependencies',
      label: t('portfolio.tab.dependencies'),
      children: <Space direction="vertical" style={{ width: '100%' }} size={12}>
        {canSubmitGovernance && <Button type="primary" icon={<PlusOutlined />} onClick={() => { dependencyForm.resetFields(); setDependencyOpen(true); }}>{t('portfolio.newDependency')}</Button>}
        {data.dependencies.length ? <Table rowKey="id" columns={dependencyColumns} dataSource={data.dependencies} pagination={false} scroll={{ x: 1100 }} /> : <Empty description={t('portfolio.noDependencies')} />}
      </Space>,
    },
    {
      key: 'resources',
      label: t('portfolio.tab.resources'),
      children: <Space direction="vertical" style={{ width: '100%' }} size={16}>
        {data.resource_conflicts.length > 0 && <Alert type="error" showIcon message={t('portfolio.conflictsDetected', { n: data.resource_conflicts.length })} description={t('portfolio.conflictsHint')} />}
        {canResource && <Button type="primary" icon={<PlusOutlined />} onClick={() => { resourceForm.resetFields(); setResourceOpen(true); }}>{t('portfolio.newCommitment')}</Button>}
        <Card size="small" title={t('portfolio.conflicts')}>
          {data.resource_conflicts.length ? <Table rowKey={(row) => `${row.person_id}-${row.start_date}`} columns={conflictColumns} dataSource={data.resource_conflicts} pagination={false} scroll={{ x: 800 }} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('portfolio.noConflicts')} />}
        </Card>
        <Card size="small" title={t('portfolio.commitments')}>
          {data.resource_commitments.length ? <Table rowKey="id" columns={commitmentColumns} dataSource={data.resource_commitments} pagination={false} scroll={{ x: 900 }} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('portfolio.noCommitments')} />}
        </Card>
      </Space>,
    },
    ...(canAudit ? [{
      key: 'audit', label: t('portfolio.tab.audit'),
      children: auditRows.length ? <Table rowKey="id" columns={auditColumns} dataSource={auditRows} pagination={{ pageSize: 20 }} scroll={{ x: 850 }} /> : <Empty description={t('portfolio.noAudit')} />,
    }] : []),
  ];

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card>
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Space wrap style={{ width: '100%', justifyContent: 'space-between' }}>
            <Space wrap>
              <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/projects/portfolios')}>{t('portfolio.back')}</Button>
              <div>
                <Typography.Title level={3} style={{ margin: 0 }}>{data.portfolio.name}</Typography.Title>
                <Typography.Text type="secondary">{data.portfolio.portfolio_code ?? '-'} · {data.portfolio.year ?? '-'}</Typography.Text>
              </div>
              <Tag color={data.portfolio.status === 'active' ? 'green' : 'default'}>{t(`portfolio.portfolioStatus.${data.portfolio.status}`)}</Tag>
            </Space>
            <Space wrap>
              <Button icon={<ReloadOutlined />} onClick={() => void load()}>{t('common.refresh')}</Button>
              {canDecide && <Button type="primary" onClick={() => { baselineForm.resetFields(); setBaselineOpen(true); }}>{t('portfolio.publishBaseline')}</Button>}
            </Space>
          </Space>
          <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 4 }}>
            <Descriptions.Item label={t('portfolio.owner')}>{data.portfolio.owner_name ?? '-'}</Descriptions.Item>
            <Descriptions.Item label={t('portfolio.period')}>{data.portfolio.planning_start ?? '-'} ~ {data.portfolio.planning_end ?? '-'}</Descriptions.Item>
            <Descriptions.Item label={t('portfolio.budgetLimit')}>{data.portfolio.budget_limit_10k == null ? '-' : `${data.portfolio.budget_limit_10k} ${t('portfolio.tenThousand')}`}</Descriptions.Item>
            <Descriptions.Item label={t('portfolio.latestBaseline')}>{data.latest_baseline ? `v${data.latest_baseline.version}` : t('portfolio.notPublished')}</Descriptions.Item>
          </Descriptions>
        </Space>
      </Card>

      <Row gutter={[12, 12]}>
        <Col xs={12} md={6}><Card size="small"><Statistic title={t('portfolio.projectCount')} value={data.summary.project_count} /></Card></Col>
        <Col xs={12} md={6}><Card size="small"><Statistic title={t('portfolio.pendingDecisions')} value={data.summary.pending_decisions} valueStyle={data.summary.pending_decisions ? { color: '#d46b08' } : undefined} /></Card></Col>
        <Col xs={12} md={6}><Card size="small"><Statistic title={t('portfolio.openDependencies')} value={data.summary.open_dependencies} /></Card></Col>
        <Col xs={12} md={6}><Card size="small"><Statistic title={t('portfolio.resourceConflicts')} value={data.summary.resource_conflict_count} valueStyle={data.summary.resource_conflict_count ? { color: '#cf1322' } : undefined} /></Card></Col>
      </Row>

      <Card title={t('portfolio.deliverySummary')}>
        <Row gutter={[16, 16]}>
          <Col xs={24} md={12}>
            <Typography.Text type="secondary">{t('portfolio.healthMix')}</Typography.Text>
            <div style={{ marginTop: 10 }}>
              <Space wrap>
                {(['green', 'yellow', 'red'] as const).map((health) => <Tag key={health} color={health === 'green' ? 'green' : health === 'yellow' ? 'gold' : 'red'}>{t(`portfolio.health.${health}`)} {data.summary.health[health] ?? 0}</Tag>)}
              </Space>
            </div>
          </Col>
          <Col xs={24} md={12}>
            <Typography.Text type="secondary">{t('portfolio.budgetExecution')}</Typography.Text>
            <Progress percent={data.summary.budget_10k ? Math.round(data.summary.actual_cost_10k / data.summary.budget_10k * 1000) / 10 : 0} status={data.summary.actual_cost_10k > data.summary.budget_10k ? 'exception' : 'normal'} />
            <Typography.Text>{data.summary.actual_cost_10k.toFixed(1)} / {data.summary.budget_10k.toFixed(1)} {t('portfolio.tenThousand')}</Typography.Text>
          </Col>
        </Row>
      </Card>

      <Card><Tabs items={tabs} /></Card>

      <Modal title={editingObjective ? t('portfolio.editObjective') : t('portfolio.newObjective')} open={objectiveOpen} confirmLoading={saving} onCancel={() => setObjectiveOpen(false)} onOk={() => void objectiveForm.validateFields().then((values) => withSave(async () => {
        const { period, ...fields } = values;
        const payload = {
          ...fields,
          period_start: period?.[0]?.format('YYYY-MM-DD') ?? null,
          period_end: period?.[1]?.format('YYYY-MM-DD') ?? null,
        };
        if (editingObjective) {
          await api.patch(`/portfolio-objectives/${editingObjective.id}`, payload);
        } else {
          await api.post(`/portfolios/${id}/objectives`, payload);
        }
        setObjectiveOpen(false);
        setEditingObjective(null);
      }))}>
        <Form form={objectiveForm} layout="vertical">
          <Form.Item name="objective_code" label={t('portfolio.objectiveCode')} rules={[{ required: true }]}><Input maxLength={32} /></Form.Item>
          <Form.Item name="name" label={t('portfolio.objective')} rules={[{ required: true, min: 2 }]}><Input maxLength={160} /></Form.Item>
          <Row gutter={12}>
            <Col span={12}><Form.Item name="metric_name" label={t('portfolio.metric')}><Input maxLength={128} /></Form.Item></Col>
            <Col span={12}><Form.Item name="target_value" label={t('portfolio.target')}><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}><Form.Item name="current_value" label={t('portfolio.current')}><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={12}><Form.Item name="weight" label={t('portfolio.weight')}><InputNumber min={0} max={100} addonAfter="%" style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}><Form.Item name="owner_id" label={t('portfolio.owner')}><Select allowClear showSearch optionFilterProp="label" options={members.map((member) => ({ value: member.id, label: member.name }))} /></Form.Item></Col>
            <Col span={12}><Form.Item name="status" label={t('common.status')} rules={[{ required: true }]}><Select options={['active', 'completed', 'archived'].map((value) => ({ value, label: t(`portfolio.objectiveStatus.${value}`) }))} /></Form.Item></Col>
          </Row>
          <Form.Item name="period" label={t('portfolio.objectivePeriod')}><DatePicker.RangePicker style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="description" label={t('portfolio.description')}><Input.TextArea rows={3} maxLength={2000} /></Form.Item>
        </Form>
      </Modal>

      <Modal title={t('portfolio.editRule')} open={!!editingRule} confirmLoading={saving} onCancel={() => setEditingRule(null)} onOk={() => void ruleForm.validateFields().then((values) => withSave(async () => {
        await api.put(`/portfolios/${id}/scoring-rules/${editingRule?.id}`, {
          ...editingRule,
          ...values,
        });
        setEditingRule(null);
      }))}>
        <Form form={ruleForm} layout="vertical">
          <Form.Item name="name" label={t('portfolio.ruleName')} rules={[{ required: true, min: 2 }]}><Input maxLength={128} /></Form.Item>
          <Row gutter={12}>
            <Col span={12}><Form.Item name="weight" label={t('portfolio.weight')} rules={[{ required: true }]}><InputNumber min={0} max={100} addonAfter="%" style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={12}><Form.Item name="sort" label={t('proj.sort')}><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
          <Space size={24}>
            <Form.Item name="evidence_required" label={t('portfolio.evidenceRequired')} valuePropName="checked"><Switch /></Form.Item>
            <Form.Item name="active" label={t('portfolio.active')} valuePropName="checked"><Switch /></Form.Item>
          </Space>
          <Form.Item name="description" label={t('portfolio.description')}><Input.TextArea rows={3} maxLength={1000} /></Form.Item>
        </Form>
      </Modal>

      <Modal width={760} title={`${t('portfolio.score')} · ${scoreProject?.name ?? ''}`} open={!!scoreProject} confirmLoading={saving} onCancel={() => setScoreProject(null)} onOk={() => void scoreForm.validateFields().then((values) => withSave(async () => {
        const scores = data.scoring_rules.filter((rule) => rule.active).map((rule) => ({ rule_id: rule.id, score: values[`score_${rule.id}`], evidence: values[`evidence_${rule.id}`] }));
        await api.put(`/portfolios/${id}/projects/${scoreProject?.project_id}/scores`, { scores });
        setScoreProject(null);
      }))}>
        <Alert type="info" showIcon message={t('portfolio.scoreHint')} style={{ marginBottom: 12 }} />
        <Form form={scoreForm} layout="vertical">
          {data.scoring_rules.filter((rule) => rule.active).map((rule) => (
            <Card key={rule.id} size="small" title={`${rule.name} (${rule.weight}%)`} style={{ marginBottom: 10 }}>
              <Row gutter={12}>
                <Col xs={24} md={7}><Form.Item name={`score_${rule.id}`} label={t('portfolio.scoreValue')} rules={[{ required: true }]}><InputNumber min={0} max={100} style={{ width: '100%' }} /></Form.Item></Col>
                <Col xs={24} md={17}><Form.Item name={`evidence_${rule.id}`} label={t('portfolio.evidence')} rules={rule.evidence_required ? [{ required: true }] : []}><Input maxLength={1000} /></Form.Item></Col>
              </Row>
            </Card>
          ))}
        </Form>
      </Modal>

      <Modal title={`${t('portfolio.contribution')} · ${contributionProject?.name ?? ''}`} open={!!contributionProject} confirmLoading={saving} onCancel={() => setContributionProject(null)} onOk={() => void contributionForm.validateFields().then((values) => withSave(async () => {
        await api.put(`/portfolios/${id}/projects/${contributionProject?.project_id}/objectives`, values);
        setContributionProject(null);
      }))}>
        <Form form={contributionForm} layout="vertical">
          <Form.List name="contributions">
            {(fields, { add, remove }) => <Space direction="vertical" style={{ width: '100%' }}>
              {fields.map((field) => <Card key={field.key} size="small">
                <Form.Item {...field} name={[field.name, 'objective_id']} label={t('portfolio.objective')} rules={[{ required: true }]}><Select options={data.objectives.filter((objective) => objective.status === 'active').map((objective) => ({ value: objective.id, label: `${objective.objective_code} ${objective.name}` }))} /></Form.Item>
                <Form.Item {...field} name={[field.name, 'weight']} label={t('portfolio.contributionWeight')} rules={[{ required: true }]}><InputNumber min={1} max={100} addonAfter="%" /></Form.Item>
                <Form.Item {...field} name={[field.name, 'note']} label={t('portfolio.note')}><Input maxLength={1000} /></Form.Item>
                <Button danger onClick={() => remove(field.name)}>{t('common.delete')}</Button>
              </Card>)}
              <Button type="dashed" block onClick={() => add()}>{t('portfolio.addContribution')}</Button>
            </Space>}
          </Form.List>
        </Form>
      </Modal>

      <Modal title={`${t('portfolio.decision')} · ${transitionProject?.name ?? ''}`} open={!!transitionProject} confirmLoading={saving} onCancel={() => setTransitionProject(null)} onOk={() => void transitionForm.validateFields().then((values) => withSave(async () => {
        await api.post(`/portfolios/${id}/projects/${transitionProject?.project_id}/transition`, values);
        setTransitionProject(null);
      }))}>
        <Form form={transitionForm} layout="vertical">
          <Form.Item name="to" label={t('portfolio.targetStatus')} rules={[{ required: true }]}><Select options={(TRANSITIONS[transitionProject?.governance_status ?? ''] ?? []).map((value) => ({ value, label: t(`portfolio.status.${value}`) }))} /></Form.Item>
          <Form.Item name="priority_rank" label={t('portfolio.priority')}><InputNumber min={1} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="reason" label={t('portfolio.reason')} rules={[{ required: true, min: 2 }]}><Input.TextArea rows={4} maxLength={2000} /></Form.Item>
        </Form>
      </Modal>

      <Modal title={t('portfolio.newDependency')} open={dependencyOpen} confirmLoading={saving} onCancel={() => setDependencyOpen(false)} onOk={() => void dependencyForm.validateFields().then((values) => withSave(async () => {
        await api.post('/project-dependencies', { ...values, due_date: values.due_date?.format('YYYY-MM-DD') });
        setDependencyOpen(false);
      }))}>
        <Form form={dependencyForm} layout="vertical">
          <Form.Item name="predecessor_project_id" label={t('portfolio.predecessor')} rules={[{ required: true }]}><Select showSearch optionFilterProp="label" options={projectOptions} /></Form.Item>
          <Form.Item name="successor_project_id" label={t('portfolio.successor')} rules={[{ required: true }]}><Select showSearch optionFilterProp="label" options={projectOptions} /></Form.Item>
          <Form.Item name="dependency_type" label={t('portfolio.dependencyType')} initialValue="finish_to_start" rules={[{ required: true }]}><Select options={['finish_to_start', 'shared_deliverable', 'shared_environment', 'external_prerequisite'].map((value) => ({ value, label: t(`portfolio.dependency.${value}`) }))} /></Form.Item>
          <Form.Item name="deliverable" label={t('portfolio.deliverable')} rules={[{ required: true, min: 2 }]}><Input maxLength={300} /></Form.Item>
          <Row gutter={12}>
            <Col span={12}><Form.Item name="due_date" label={t('portfolio.dueDate')}><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={12}><Form.Item name="impact" label={t('portfolio.impact')} initialValue="medium"><Select options={['low', 'medium', 'high'].map((value) => ({ value, label: t(`portfolio.impact.${value}`) }))} /></Form.Item></Col>
          </Row>
          <Form.Item name="owner_id" label={t('portfolio.owner')}><Select allowClear showSearch optionFilterProp="label" options={members.map((member) => ({ value: member.id, label: member.name }))} /></Form.Item>
        </Form>
      </Modal>

      <Modal title={t('portfolio.newCommitment')} open={resourceOpen} confirmLoading={saving} onCancel={() => setResourceOpen(false)} onOk={() => void resourceForm.validateFields().then((values: { period: [Dayjs, Dayjs]; [key: string]: unknown }) => withSave(async () => {
        const { period, ...rest } = values;
        await api.post('/project-resource-commitments', { ...rest, start_date: period[0].format('YYYY-MM-DD'), end_date: period[1].format('YYYY-MM-DD') });
        setResourceOpen(false);
      }))}>
        <Form form={resourceForm} layout="vertical">
          <Form.Item name="project_id" label={t('portfolio.project')} rules={[{ required: true }]}><Select showSearch optionFilterProp="label" options={projectOptions} /></Form.Item>
          <Form.Item name="person_id" label={t('portfolio.person')} rules={[{ required: true }]}><Select showSearch optionFilterProp="label" options={members.map((member) => ({ value: member.id, label: member.name }))} /></Form.Item>
          <Form.Item name="role_name" label={t('portfolio.role')}><Input maxLength={96} /></Form.Item>
          <Form.Item name="period" label={t('portfolio.period')} rules={[{ required: true }]}><DatePicker.RangePicker style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="allocation_percent" label={t('portfolio.allocation')} rules={[{ required: true }]}><InputNumber min={1} max={100} addonAfter="%" style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="note" label={t('portfolio.note')}><Input.TextArea rows={3} maxLength={2000} /></Form.Item>
        </Form>
      </Modal>

      <Modal title={t('portfolio.publishBaseline')} open={baselineOpen} confirmLoading={saving} onCancel={() => setBaselineOpen(false)} onOk={() => void baselineForm.validateFields().then((values) => withSave(async () => {
        await api.post(`/portfolios/${id}/baselines`, values);
        setBaselineOpen(false);
      }))}>
        <Alert type="warning" showIcon message={t('portfolio.baselineWarning')} description={t('portfolio.baselineHint')} style={{ marginBottom: 12 }} />
        <Form form={baselineForm} layout="vertical">
          <Form.Item name="reason" label={t('portfolio.reason')} rules={[{ required: true, min: 2 }]}><Input.TextArea rows={4} maxLength={2000} /></Form.Item>
        </Form>
      </Modal>
    </Space>
  );
}
