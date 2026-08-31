import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  DownloadOutlined,
  FileAddOutlined,
  ReloadOutlined,
  SendOutlined,
} from '@ant-design/icons';
import dayjs, { type Dayjs } from 'dayjs';
import { api } from '../../api/client';
import Table from '../../components/SortableTable';
import InvestmentPanel from '../../components/investment/InvestmentPanel';
import { useT } from '../../i18n';
import { useLangStore } from '../../i18n/store';
import { ALL_ROLES, ROLE_LABELS, type Role } from '../../api/types';

type ReportTab = 'overview' | 'project' | 'requirement' | 'operations' | 'people' | 'platform' | 'library' | 'catalog';

interface MetricDefinition {
  code: string;
  domain: 'itsm' | 'project' | 'requirement' | 'operations' | 'people' | 'task' | 'process' | 'platform';
  name_zh: string;
  name_en: string;
  unit: string;
  kind: 'scalar' | 'series';
  sensitivity: 'normal' | 'finance' | 'people' | 'platform';
  formula_version: string;
}

interface MetricResult extends MetricDefinition {
  value: number | string | null | Array<{ key: string; value: number | string | null; sample_size?: number }>;
  quality: 'ok' | 'no_data' | 'suppressed';
}

interface MetricQueryResult {
  period_start: string;
  period_end: string;
  filters: Record<string, string>;
  metrics: MetricResult[];
}

interface ReportTemplate {
  id: string;
  code: string;
  name: string;
  description?: string | null;
  metric_codes: string[];
  available_metric_codes: string[];
  restricted_metric_count: number;
  default_period_type: string;
}

interface ReportRow {
  id: string;
  template_id: string;
  title: string;
  period_type: string;
  period_start: string;
  period_end: string;
  status: 'draft' | 'review' | 'approved' | 'published';
  current_version: number;
  published_version: number;
  process_instance_id?: string | null;
  published_at?: string | null;
}

interface ReportVersion {
  id: string;
  version: number;
  status: string;
  metric_snapshot: MetricQueryResult;
  narrative: Record<string, unknown>;
  checksum: string;
  generated_at: string;
  locked_at?: string | null;
}

interface ReportDetail extends ReportRow {
  version: ReportVersion | null;
  audience?: Array<{ subject_type: string; subject_id: string }>;
}

interface ProjectRef {
  id: string;
  project_code: string;
  name: string;
}

const TAB_DOMAINS: Record<Exclude<ReportTab, 'library' | 'catalog'>, MetricDefinition['domain'][] | null> = {
  overview: null,
  project: ['project'],
  requirement: ['requirement'],
  operations: ['operations'],
  people: ['people'],
  platform: ['platform'],
};

const OVERVIEW_CODES = [
  'itsm.ticket_count', 'itsm.sla_resolution_rate', 'project.active_count',
  'requirement.avg_lead_days', 'operations.incurred_cost_cny',
  'operations.effort_days', 'people.effort_days', 'task.completed_count',
  'process.avg_cycle_hours',
];

const statusColor: Record<string, string> = {
  draft: 'default', review: 'processing', approved: 'success', published: 'blue', locked: 'purple',
};

function idempotencyKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `report-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function displayMetricValue(metric: MetricResult): string | number {
  if (metric.value == null) return '-';
  if (Array.isArray(metric.value)) return metric.value.length;
  const numeric = Number(metric.value);
  if (metric.unit === 'CNY' && Number.isFinite(numeric)) {
    return new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY', maximumFractionDigits: 2 }).format(numeric);
  }
  if (metric.unit === 'percent') return `${numeric}%`;
  return metric.value;
}

function MetricSeries({ items }: { items: Array<{ key: string; value: number | string | null; sample_size?: number }> }) {
  const max = Math.max(...items.map((item) => Number(item.value || 0)), 1);
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      {items.map((item) => {
        const numeric = Number(item.value || 0);
        return (
          <div key={item.key}>
            <Space style={{ width: '100%', justifyContent: 'space-between' }}>
              <Typography.Text>{item.key}</Typography.Text>
              <Typography.Text>{item.value ?? '-'}</Typography.Text>
            </Space>
            <Progress percent={Math.min(100, Math.max(0, numeric / max * 100))} showInfo={false} size="small" />
          </div>
        );
      })}
    </Space>
  );
}

function MetricCards({ metrics, onDrilldown }: { metrics: MetricResult[]; onDrilldown: (metric: MetricResult) => void }) {
  const t = useT();
  const lang = useLangStore((state) => state.lang);
  if (!metrics.length) return <Empty description={t('report.noData')} />;
  return (
    <Row gutter={[16, 16]}>
      {metrics.map((metric) => (
        <Col xs={24} sm={12} xl={8} key={metric.code}>
          <Card
            size="small"
            hoverable={metric.kind === 'scalar'}
            onClick={() => metric.kind === 'scalar' && onDrilldown(metric)}
            title={lang === 'en' ? metric.name_en : metric.name_zh}
            extra={<Typography.Text type="secondary">v{metric.formula_version}</Typography.Text>}
          >
            {metric.kind === 'series' && Array.isArray(metric.value) ? (
              <MetricSeries items={metric.value} />
            ) : (
              <Statistic value={displayMetricValue(metric)} />
            )}
            {metric.quality !== 'ok' && <Tag style={{ marginTop: 8 }}>{t('report.quality.noData')}</Tag>}
          </Card>
        </Col>
      ))}
    </Row>
  );
}

export default function ReportCenter() {
  const t = useT();
  const lang = useLangStore((state) => state.lang);
  const [tab, setTab] = useState<ReportTab>('overview');
  const [period, setPeriod] = useState<[Dayjs, Dayjs]>([dayjs().startOf('month'), dayjs().endOf('month')]);
  const [catalog, setCatalog] = useState<MetricDefinition[]>([]);
  const [templates, setTemplates] = useState<ReportTemplate[]>([]);
  const [reports, setReports] = useState<ReportRow[]>([]);
  const [projects, setProjects] = useState<ProjectRef[]>([]);
  const [projectId, setProjectId] = useState<string>();
  const [queryResult, setQueryResult] = useState<MetricQueryResult>();
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createSaving, setCreateSaving] = useState(false);
  const [createForm] = Form.useForm();
  const [detail, setDetail] = useState<ReportDetail>();
  const [narrative, setNarrative] = useState('');
  const [publishTarget, setPublishTarget] = useState<ReportRow>();
  const [audienceRoles, setAudienceRoles] = useState<Role[]>(['cio']);
  const [drilldown, setDrilldown] = useState<{ metric: MetricResult; rows: Record<string, unknown>[] }>();

  const loadReferenceData = useCallback(async () => {
    const [metricRows, templateRows, reportRows, projectRows] = await Promise.all([
      api.get<MetricDefinition[]>('/reports/metrics'),
      api.get<ReportTemplate[]>('/reports/templates'),
      api.getList<ReportRow>('/reports'),
      api.getList<ProjectRef>('/projects', { page: 1, page_size: 200 }),
    ]);
    setCatalog(metricRows);
    setTemplates(templateRows);
    setReports(reportRows.items);
    setProjects(projectRows.items);
  }, []);

  useEffect(() => {
    void loadReferenceData();
  }, [loadReferenceData]);

  const activeMetricCodes = useMemo(() => {
    if (tab === 'library' || tab === 'catalog') return [];
    if (tab === 'overview') return OVERVIEW_CODES.filter((code) => catalog.some((item) => item.code === code));
    const domains = TAB_DOMAINS[tab];
    return catalog.filter((item) => domains?.includes(item.domain)).map((item) => item.code);
  }, [catalog, tab]);

  const runQuery = useCallback(async () => {
    if (!activeMetricCodes.length) return;
    setLoading(true);
    try {
      const filters = tab === 'project' && projectId ? { project_id: projectId } : {};
      setQueryResult(await api.post<MetricQueryResult>('/reports/query', {
        metric_codes: activeMetricCodes,
        period_start: period[0].format('YYYY-MM-DD'),
        period_end: period[1].format('YYYY-MM-DD'),
        filters,
      }));
    } finally {
      setLoading(false);
    }
  }, [activeMetricCodes, period, projectId, tab]);

  useEffect(() => {
    if (tab !== 'library' && tab !== 'catalog') void runQuery();
  }, [runQuery, tab]);

  const openDrilldown = async (metric: MetricResult) => {
    try {
      const rows = await api.get<Record<string, unknown>[]>(`/reports/drilldown/${metric.code}`, {
        period_start: period[0].format('YYYY-MM-DD'), period_end: period[1].format('YYYY-MM-DD'), limit: 200,
        ...(tab === 'project' && projectId ? { project_id: projectId } : {}),
      });
      setDrilldown({ metric, rows });
    } catch {
      // 部分聚合指标不提供明细，后端已给出明确提示。
    }
  };

  const createReport = async () => {
    const values = await createForm.validateFields();
    setCreateSaving(true);
    try {
      const range = values.period as [Dayjs, Dayjs];
      const created = await api.post<ReportRow>('/reports', {
        template_id: values.template_id, title: values.title, period_type: 'custom',
        period_start: range[0].format('YYYY-MM-DD'), period_end: range[1].format('YYYY-MM-DD'),
        filters: tab === 'project' && projectId ? { project_id: projectId } : {},
      });
      await api.postWithHeaders(`/reports/${created.id}/generate`, {}, { 'Idempotency-Key': idempotencyKey() });
      message.success(t('report.created'));
      setCreateOpen(false);
      createForm.resetFields();
      await loadReferenceData();
    } finally {
      setCreateSaving(false);
    }
  };

  const loadDetail = async (row: ReportRow) => {
    const value = await api.get<ReportDetail>(`/reports/${row.id}`);
    setDetail(value);
    setNarrative(String(value.version?.narrative?.summary ?? ''));
  };

  const refreshDetail = async (reportId: string) => {
    const value = await api.get<ReportDetail>(`/reports/${reportId}`);
    setDetail(value);
    setReports((current) => current.map((row) => (row.id === value.id ? value : row)));
  };

  const generateVersion = async (row: ReportRow) => {
    await api.postWithHeaders(`/reports/${row.id}/generate`, {}, { 'Idempotency-Key': idempotencyKey() });
    await loadReferenceData();
    if (detail?.id === row.id) await refreshDetail(row.id);
  };

  const submitReview = async (row: ReportRow) => {
    await api.post(`/reports/${row.id}/submit-review`, {});
    message.success(t('report.submitted'));
    await loadReferenceData();
    if (detail?.id === row.id) await refreshDetail(row.id);
  };

  const publish = async () => {
    if (!publishTarget) return;
    await api.post(`/reports/${publishTarget.id}/publish`, {
      audience: audienceRoles.map((role) => ({ subject_type: 'role', subject_id: role })),
    });
    message.success(t('report.published'));
    setPublishTarget(undefined);
    await loadReferenceData();
    if (detail?.id === publishTarget.id) await refreshDetail(publishTarget.id);
  };

  const saveNarrative = async () => {
    if (!detail) return;
    const value = await api.patch<ReportVersion>(`/reports/${detail.id}/narrative`, { narrative: { summary: narrative } });
    setDetail({ ...detail, version: value });
    message.success(t('report.saved'));
  };

  const reportColumns: ColumnsType<ReportRow> = [
    { title: t('report.reportTitle'), dataIndex: 'title', width: 260, fixed: 'left' },
    { title: t('report.period'), key: 'period', width: 220, render: (_, row) => `${row.period_start} ~ ${row.period_end}` },
    { title: t('common.status'), dataIndex: 'status', width: 110, render: (value: string) => <Tag color={statusColor[value]}>{t(`report.status.${value}`)}</Tag> },
    { title: t('report.currentVersion'), dataIndex: 'current_version', width: 110 },
    { title: t('report.publishedVersion'), dataIndex: 'published_version', width: 120, render: (value: number) => value || '-' },
    {
      title: t('common.actions'), key: 'actions', width: 410, fixed: 'right',
      render: (_, row) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => void loadDetail(row)}>{t('report.view')}</Button>
          <Button type="link" size="small" disabled={row.status === 'review' || row.status === 'approved'} onClick={() => void generateVersion(row)}>{t('report.generate')}</Button>
          <Button type="link" size="small" icon={<SendOutlined />} disabled={row.status !== 'draft' || !row.current_version} onClick={() => void submitReview(row)}>{t('report.submitReview')}</Button>
          <Button type="link" size="small" disabled={row.status !== 'approved'} onClick={() => setPublishTarget(row)}>{t('report.publish')}</Button>
          <Button type="link" size="small" icon={<DownloadOutlined />} disabled={!row.published_version} onClick={() => void api.download(`/reports/${row.id}/export`)}>{t('report.export')}</Button>
        </Space>
      ),
    },
  ];

  const catalogColumns: ColumnsType<MetricDefinition> = [
    { title: t('report.catalog.code'), dataIndex: 'code', width: 250, fixed: 'left' },
    { title: t('report.catalog.name'), key: 'name', width: 200, render: (_, row) => lang === 'en' ? row.name_en : row.name_zh },
    { title: t('report.catalog.domain'), dataIndex: 'domain', width: 120 },
    { title: t('report.catalog.unit'), dataIndex: 'unit', width: 110 },
    { title: t('report.catalog.sensitivity'), dataIndex: 'sensitivity', width: 140 },
    { title: t('report.catalog.formula'), dataIndex: 'formula_version', width: 120 },
  ];

  const tabs = [
    { key: 'overview', label: t('report.tab.overview') },
    { key: 'project', label: t('report.tab.project') },
    { key: 'requirement', label: t('report.tab.requirement') },
    { key: 'operations', label: t('report.tab.operations') },
    { key: 'people', label: t('report.tab.people') },
    { key: 'platform', label: t('report.tab.platform') },
    { key: 'library', label: t('report.tab.library') },
    { key: 'catalog', label: t('report.tab.catalog') },
  ];

  return (
    <Card title={t('report.title')} extra={<Button type="primary" icon={<FileAddOutlined />} onClick={() => {
      createForm.setFieldsValue({ period, template_id: templates[0]?.id });
      setCreateOpen(true);
    }}>{t('report.new')}</Button>}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Alert type="info" showIcon message={t('report.subtitle')} />
        <Tabs activeKey={tab} items={tabs} onChange={(key) => setTab(key as ReportTab)} />
        {tab !== 'library' && tab !== 'catalog' && (
          <Space wrap>
            <Typography.Text>{t('report.period')}</Typography.Text>
            <DatePicker.RangePicker value={period} allowClear={false} onChange={(value) => value && setPeriod(value as [Dayjs, Dayjs])} />
            {tab === 'project' && (
              <Select
                allowClear showSearch optionFilterProp="label" style={{ width: 340 }} value={projectId}
                placeholder={t('report.allProjects')} onChange={setProjectId}
                options={projects.map((row) => ({ value: row.id, label: `${row.project_code} ${row.name}` }))}
              />
            )}
            <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void runQuery()}>{t('report.refresh')}</Button>
            <Typography.Text type="secondary">{t('report.filtersApplied')}</Typography.Text>
          </Space>
        )}
        {tab === 'library' ? (
          <Table<ReportRow> rowKey="id" columns={reportColumns} dataSource={reports} scroll={{ x: 'max-content' }} pagination={{ pageSize: 20 }} />
        ) : tab === 'catalog' ? (
          <Table<MetricDefinition> rowKey="code" columns={catalogColumns} dataSource={catalog} scroll={{ x: 'max-content' }} pagination={{ pageSize: 20 }} />
        ) : (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <MetricCards metrics={queryResult?.metrics ?? []} onDrilldown={(metric) => void openDrilldown(metric)} />
            {tab === 'operations' && (
              <InvestmentPanel
                subjectType="shared_operations"
                lifecycleStage="run"
                title={t('report.sharedOperationsLedger')}
              />
            )}
          </Space>
        )}
      </Space>

      <Modal title={t('report.new')} open={createOpen} onOk={() => void createReport()} confirmLoading={createSaving} onCancel={() => setCreateOpen(false)} destroyOnClose>
        <Form form={createForm} layout="vertical" preserve={false}>
          <Form.Item name="template_id" label={t('report.template')} rules={[{ required: true }]}>
            <Select options={templates.filter((row) => row.restricted_metric_count === 0).map((row) => ({ value: row.id, label: row.name }))} />
          </Form.Item>
          <Form.Item name="title" label={t('report.reportTitle')} rules={[{ required: true, min: 2 }]}><Input maxLength={200} /></Form.Item>
          <Form.Item name="period" label={t('report.period')} rules={[{ required: true }]}><DatePicker.RangePicker style={{ width: '100%' }} /></Form.Item>
        </Form>
      </Modal>

      <Modal title={t('report.publish')} open={!!publishTarget} onOk={() => void publish()} onCancel={() => setPublishTarget(undefined)}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Typography.Text>{t('report.audience')}</Typography.Text>
          <Select mode="multiple" style={{ width: '100%' }} value={audienceRoles} onChange={setAudienceRoles}
            options={ALL_ROLES.map((role) => ({ value: role, label: ROLE_LABELS[role] }))} />
          <Alert type="warning" showIcon message={t('report.audienceHint')} />
        </Space>
      </Modal>

      <Drawer title={detail?.title} width={760} open={!!detail} onClose={() => setDetail(undefined)}>
        {detail?.version ? (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Space>
              <Tag color={statusColor[detail.status]}>{t(`report.status.${detail.status}`)}</Tag>
              <Typography.Text>{t('report.version')} {detail.version.version}</Typography.Text>
              <Typography.Text type="secondary">{detail.version.checksum.slice(0, 12)}</Typography.Text>
            </Space>
            <Input.TextArea rows={5} value={narrative} disabled={detail.status !== 'draft'} onChange={(event) => setNarrative(event.target.value)} placeholder={t('report.narrative')} />
            {detail.status === 'draft' && <Button type="primary" onClick={() => void saveNarrative()}>{t('report.saveNarrative')}</Button>}
            <MetricCards metrics={detail.version.metric_snapshot.metrics} onDrilldown={(metric) => void openDrilldown(metric)} />
          </Space>
        ) : <Empty />}
      </Drawer>

      <Drawer title={`${t('report.drilldown')} · ${drilldown ? (lang === 'en' ? drilldown.metric.name_en : drilldown.metric.name_zh) : ''}`} width={900} open={!!drilldown} onClose={() => setDrilldown(undefined)}>
        {drilldown && (
          <Table<Record<string, unknown>>
            rowKey={(row) => String(row.id)}
            dataSource={drilldown.rows}
            columns={Object.keys(drilldown.rows[0] ?? {}).map((key) => ({ title: key, dataIndex: key, width: 160 }))}
            scroll={{ x: 'max-content' }} pagination={{ pageSize: 20 }}
          />
        )}
      </Drawer>
    </Card>
  );
}
