import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Progress,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  BranchesOutlined,
  CheckOutlined,
  EditOutlined,
  EyeOutlined,
  PlusOutlined,
  ReloadOutlined,
  SendOutlined,
} from '@ant-design/icons';
import { api } from '../../api/client';
import type { BusinessDomain, Member } from '../../api/types';
import Table from '../../components/SortableTable';
import { useT } from '../../i18n';
import { hasPermission, useAuthStore } from '../../stores/auth';


export type PlatformPane = 'services' | 'demands' | 'capacity';

interface ServiceItemRef {
  id: string;
  item_code: string;
  name: string;
  status: string;
}

interface RequirementRef {
  id: string;
  requirement_code: string;
  title: string;
  status: string;
  business_domain_id: string;
  business_domain_name?: string;
}

interface PlatformService {
  id: string;
  service_item_id: string;
  item_code: string;
  name: string;
  service_type?: string | null;
  status?: string | null;
  owner_id?: string | null;
  owner_name?: string | null;
  lifecycle: string;
  value_proposition?: string | null;
  management_scope: Record<string, unknown>;
  updated_at: string;
}

interface PlatformDemand {
  id: string;
  requirement_id: string;
  requirement_code: string;
  title: string;
  requirement_status: string;
  service_item_id: string;
  service_name: string;
  business_domain_id: string;
  business_domain_name: string;
  demand_class: string;
  expected_outcome: string;
  target_quarter: string;
  capacity_class: string;
  updated_at: string;
}

interface CapacityCommitment {
  id: string;
  plan_id: string;
  subject_type: string;
  subject_id?: string | null;
  title: string;
  commitment_type: string;
  capacity_days: string;
  lifecycle_stage: string;
  investment_intent: string;
  owner_id?: string | null;
  owner_name?: string | null;
  status: string;
  over_capacity_reason?: string | null;
  over_capacity_approved_by?: string | null;
}

interface CapacityPlan {
  id: string;
  service_item_id: string;
  service_name: string;
  period: string;
  version: number;
  status: string;
  gross_days: string;
  planned_unavailable_days: string;
  bau_reserve_days: string;
  risk_buffer_days: string;
  net_days: string;
  committed_days: string;
  remaining_days: string;
  utilization_percent?: string | null;
  notes?: string | null;
  approval_reason?: string | null;
  approved_at?: string | null;
  previous_version_id?: string | null;
  commitments?: CapacityCommitment[];
}

const LIFECYCLE_OPTIONS = ['candidate', 'pilot', 'active', 'retiring', 'retired'];
const DEMAND_CLASS_OPTIONS = ['business', 'product', 'technology', 'reliability', 'compliance'];
const CAPACITY_CLASS_OPTIONS = ['small', 'medium', 'large', 'expedite'];
const STATUS_COLOR: Record<string, string> = {
  candidate: 'default', pilot: 'processing', active: 'success', retiring: 'warning', retired: 'default',
  draft: 'default', review: 'processing', approved: 'success', superseded: 'default',
  planned: 'default', completed: 'success', cancelled: 'default',
};

function idempotencyKey(prefix: string): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? `${prefix}-${crypto.randomUUID()}`
    : `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function currentQuarter(): string {
  const now = new Date();
  return `${now.getFullYear()}-Q${Math.floor(now.getMonth() / 3) + 1}`;
}

function quarterOptions() {
  const now = new Date();
  const values: string[] = [];
  for (let year = now.getFullYear() - 1; year <= now.getFullYear() + 2; year += 1) {
    for (let quarter = 1; quarter <= 4; quarter += 1) values.push(`${year}-Q${quarter}`);
  }
  return values.map((value) => ({ value, label: value }));
}

function scopeText(scope: Record<string, unknown>): string {
  const note = scope?.scope_note;
  if (typeof note === 'string' && note.trim()) return note;
  return Object.keys(scope ?? {}).length ? JSON.stringify(scope) : '-';
}

export default function PlatformOperations({ pane }: { pane: PlatformPane }) {
  const t = useT();
  const user = useAuthStore((state) => state.user);
  const canPortfolioCreate = !!user && (!user.permissions || hasPermission(user, 'platform_portfolio', 'create'));
  const canPortfolioEdit = !!user && (!user.permissions || hasPermission(user, 'platform_portfolio', 'edit'));
  const canCapacityCreate = !!user && (!user.permissions || hasPermission(user, 'platform_capacity', 'create'));
  const canCapacityEdit = !!user && (!user.permissions || hasPermission(user, 'platform_capacity', 'edit'));
  const canApproveCapacity = canCapacityEdit && !!user?.roles.some((role) => role === 'cio' || role === 'it_pdm_leader');
  const canOverrideCapacity = !!user?.roles.includes('cio');

  const [services, setServices] = useState<PlatformService[]>([]);
  const [demands, setDemands] = useState<PlatformDemand[]>([]);
  const [plans, setPlans] = useState<CapacityPlan[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState('');
  const [serviceItems, setServiceItems] = useState<ServiceItemRef[]>([]);
  const [requirements, setRequirements] = useState<RequirementRef[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [domains, setDomains] = useState<BusinessDomain[]>([]);
  const [serviceModal, setServiceModal] = useState(false);
  const [editingService, setEditingService] = useState<PlatformService>();
  const [demandModal, setDemandModal] = useState(false);
  const [editingDemand, setEditingDemand] = useState<PlatformDemand>();
  const [planModal, setPlanModal] = useState(false);
  const [commitmentModal, setCommitmentModal] = useState(false);
  const [revisionModal, setRevisionModal] = useState(false);
  const [approvalModal, setApprovalModal] = useState(false);
  const [selectedPlan, setSelectedPlan] = useState<CapacityPlan>();
  const [saving, setSaving] = useState(false);
  const [serviceForm] = Form.useForm();
  const [demandForm] = Form.useForm();
  const [planForm] = Form.useForm();
  const [commitmentForm] = Form.useForm();
  const [revisionForm] = Form.useForm();
  const [approvalForm] = Form.useForm();
  const allowOvercommit = Form.useWatch('allow_overcommit', commitmentForm);
  const selectedRequirementId = Form.useWatch('requirement_id', demandForm);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { page, page_size: pageSize, q: q || undefined };
      if (pane === 'services') {
        const result = await api.getList<PlatformService>('/platform/services', params);
        setServices(result.items); setTotal(result.total);
      } else if (pane === 'demands') {
        const result = await api.getList<PlatformDemand>('/platform/demands', params);
        setDemands(result.items); setTotal(result.total);
      } else {
        const result = await api.getList<CapacityPlan>('/platform/capacity-plans', { page, page_size: pageSize });
        setPlans(result.items); setTotal(result.total);
      }
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, pane, q]);

  const loadReferences = useCallback(async () => {
    const jobs: Array<Promise<void>> = [
      api.getList<ServiceItemRef>('/service-items', { page: 1, page_size: 200 }).then((result) => setServiceItems(result.items)),
      api.getList<Member>('/members', { page: 1, page_size: 2000, scope: 'it' }).then((result) => setMembers(result.items)),
      api.getList<RequirementRef>('/requirements', { page: 1, page_size: 200 }).then((result) => setRequirements(result.items)),
    ];
    if (pane !== 'services') jobs.push(
      api.getList<PlatformService>('/platform/services', { page: 1, page_size: 200 }).then((result) => setServices(result.items)),
    );
    if (pane !== 'demands') jobs.push(
      api.getList<PlatformDemand>('/platform/demands', { page: 1, page_size: 200 }).then((result) => setDemands(result.items)),
    );
    jobs.push(api.getList<BusinessDomain>('/admin/business-domains', { page: 1, page_size: 200 })
      .then((result) => setDomains(result.items)).catch(() => undefined));
    await Promise.all(jobs);
  }, [pane]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { void loadReferences(); }, [loadReferences]);
  useEffect(() => { setPage(1); setQ(''); }, [pane]);

  useEffect(() => {
    if (!selectedRequirementId || editingDemand) return;
    const requirement = requirements.find((item) => item.id === selectedRequirementId);
    if (requirement) demandForm.setFieldValue('business_domain_id', requirement.business_domain_id);
  }, [demandForm, editingDemand, requirements, selectedRequirementId]);

  const memberOptions = useMemo(() => members.map((item) => ({ value: item.id, label: item.name })), [members]);
  const platformServiceOptions = useMemo(
    () => services.map((item) => ({ value: item.service_item_id, label: `${item.item_code} ${item.name}` })),
    [services],
  );
  const domainOptions = useMemo(() => {
    const map = new Map(domains.map((item) => [item.id, item.name]));
    requirements.forEach((item) => {
      if (!map.has(item.business_domain_id)) map.set(item.business_domain_id, item.business_domain_name || item.business_domain_id);
    });
    return Array.from(map, ([value, label]) => ({ value, label }));
  }, [domains, requirements]);

  const refreshPlan = async (planId: string) => {
    const detail = await api.get<CapacityPlan>(`/platform/capacity-plans/${planId}`);
    setSelectedPlan(detail);
    await load();
  };

  const openService = (row?: PlatformService) => {
    setEditingService(row);
    serviceForm.resetFields();
    if (row) serviceForm.setFieldsValue({
      service_item_id: row.service_item_id, owner_id: row.owner_id, lifecycle: row.lifecycle,
      value_proposition: row.value_proposition, scope_note: scopeText(row.management_scope) === '-' ? '' : scopeText(row.management_scope),
      lifecycle_change_reason: undefined,
    });
    else serviceForm.setFieldsValue({ lifecycle: 'candidate' });
    setServiceModal(true);
  };

  const saveService = async () => {
    const values = await serviceForm.validateFields();
    setSaving(true);
    try {
      const payload = {
        owner_id: values.owner_id ?? null, lifecycle: values.lifecycle,
        value_proposition: values.value_proposition || null,
        management_scope: values.scope_note ? { scope_note: values.scope_note } : {},
        lifecycle_change_reason: values.lifecycle_change_reason || null,
      };
      if (editingService) await api.patch(`/platform/services/${editingService.service_item_id}`, payload);
      else await api.post('/platform/services', { service_item_id: values.service_item_id, ...payload });
      message.success(t('platform.saved'));
      setServiceModal(false); await load();
    } finally { setSaving(false); }
  };

  const openDemand = (row?: PlatformDemand) => {
    setEditingDemand(row);
    demandForm.resetFields();
    if (row) demandForm.setFieldsValue(row);
    else demandForm.setFieldsValue({ target_quarter: currentQuarter(), demand_class: 'business', capacity_class: 'medium' });
    setDemandModal(true);
  };

  const saveDemand = async () => {
    const values = await demandForm.validateFields();
    setSaving(true);
    try {
      if (editingDemand) {
        const { requirement_id: _, ...payload } = values;
        await api.patch(`/platform/demands/${editingDemand.requirement_id}`, payload);
      } else await api.post('/platform/demands', values);
      message.success(t('platform.saved'));
      setDemandModal(false); await load();
    } finally { setSaving(false); }
  };

  const savePlan = async () => {
    const values = await planForm.validateFields();
    setSaving(true);
    try {
      await api.postWithHeaders('/platform/capacity-plans', values, { 'Idempotency-Key': idempotencyKey('capacity-plan') });
      message.success(t('platform.saved'));
      setPlanModal(false); await load();
    } finally { setSaving(false); }
  };

  const saveCommitment = async () => {
    if (!selectedPlan) return;
    const values = await commitmentForm.validateFields();
    setSaving(true);
    try {
      await api.postWithHeaders(`/platform/capacity-plans/${selectedPlan.id}/commitments`, values, {
        'Idempotency-Key': idempotencyKey('capacity-commitment'),
      });
      message.success(t('platform.commitmentAdded'));
      setCommitmentModal(false); await refreshPlan(selectedPlan.id);
    } finally { setSaving(false); }
  };

  const submitPlan = async (row: CapacityPlan) => {
    await api.post(`/platform/capacity-plans/${row.id}/submit`, {});
    message.success(t('platform.submitted')); await refreshPlan(row.id);
  };

  const approvePlan = async () => {
    if (!selectedPlan) return;
    const values = await approvalForm.validateFields();
    setSaving(true);
    try {
      await api.post(`/platform/capacity-plans/${selectedPlan.id}/approve`, values);
      message.success(t('platform.approved')); setApprovalModal(false); await refreshPlan(selectedPlan.id);
    } finally { setSaving(false); }
  };

  const saveRevision = async () => {
    if (!selectedPlan) return;
    const values = await revisionForm.validateFields();
    setSaving(true);
    try {
      const row = await api.postWithHeaders<CapacityPlan>(`/platform/capacity-plans/${selectedPlan.id}/revisions`, values, {
        'Idempotency-Key': idempotencyKey('capacity-revision'),
      });
      message.success(t('platform.revised')); setRevisionModal(false); setSelectedPlan(row); await load();
    } finally { setSaving(false); }
  };

  const viewPlan = async (row: CapacityPlan) => setSelectedPlan(await api.get<CapacityPlan>(`/platform/capacity-plans/${row.id}`));

  const serviceColumns: ColumnsType<PlatformService> = [
    { title: '服务编号', dataIndex: 'item_code', fixed: 'left' },
    { title: '服务名称', dataIndex: 'name', fixed: 'left' },
    { title: t('platform.owner'), dataIndex: 'owner_name', render: (value) => value || '-' },
    { title: t('platform.lifecycle'), dataIndex: 'lifecycle', render: (value) => <Tag color={STATUS_COLOR[value]}>{value}</Tag> },
    { title: t('platform.value'), dataIndex: 'value_proposition', render: (value) => value || '-' },
    { title: t('platform.scope'), dataIndex: 'management_scope', render: (value) => scopeText(value) },
    { title: t('common.status'), dataIndex: 'status', render: (value) => value || '-' },
    { title: t('common.actions'), key: 'actions', fixed: 'right', width: 76, render: (_, row) => canPortfolioEdit && (
      <Button type="text" icon={<EditOutlined />} aria-label={t('common.edit')} onClick={() => openService(row)} />
    ) },
  ];

  const demandColumns: ColumnsType<PlatformDemand> = [
    { title: '需求编号', dataIndex: 'requirement_code', fixed: 'left' },
    { title: '需求标题', dataIndex: 'title', fixed: 'left' },
    { title: t('platform.service'), dataIndex: 'service_name' },
    { title: t('platform.domain'), dataIndex: 'business_domain_name' },
    { title: t('platform.demandClass'), dataIndex: 'demand_class' },
    { title: t('platform.expectedOutcome'), dataIndex: 'expected_outcome' },
    { title: t('platform.targetQuarter'), dataIndex: 'target_quarter' },
    { title: t('platform.capacityClass'), dataIndex: 'capacity_class' },
    { title: t('common.status'), dataIndex: 'requirement_status' },
    { title: t('common.actions'), key: 'actions', fixed: 'right', width: 76, render: (_, row) => canPortfolioCreate && (
      <Button type="text" icon={<EditOutlined />} aria-label={t('common.edit')} onClick={() => openDemand(row)} />
    ) },
  ];

  const planColumns: ColumnsType<CapacityPlan> = [
    { title: t('platform.service'), dataIndex: 'service_name', fixed: 'left' },
    { title: t('platform.period'), dataIndex: 'period', fixed: 'left' },
    { title: t('platform.version'), dataIndex: 'version', render: (value) => `v${value}` },
    { title: t('common.status'), dataIndex: 'status', render: (value) => <Tag color={STATUS_COLOR[value]}>{value}</Tag> },
    { title: t('platform.grossDays'), dataIndex: 'gross_days' },
    { title: t('platform.netDays'), dataIndex: 'net_days' },
    { title: t('platform.committedDays'), dataIndex: 'committed_days' },
    { title: t('platform.remainingDays'), dataIndex: 'remaining_days' },
    { title: t('platform.utilization'), dataIndex: 'utilization_percent', render: (value) => value == null ? '-' : `${value}%` },
    { title: t('common.actions'), key: 'actions', fixed: 'right', width: 76, render: (_, row) => (
      <Button type="text" icon={<EyeOutlined />} aria-label={t('common.detail')} onClick={() => void viewPlan(row)} />
    ) },
  ];

  const titleKey = `platform.title.${pane}`;
  const createButton = pane === 'services' && canPortfolioEdit
    ? <Button type="primary" icon={<PlusOutlined />} onClick={() => openService()}>{t('platform.enableService')}</Button>
    : pane === 'demands' && canPortfolioCreate
      ? <Button type="primary" icon={<PlusOutlined />} onClick={() => openDemand()}>{t('platform.addDemand')}</Button>
      : pane === 'capacity' && canCapacityCreate
        ? <Button type="primary" icon={<PlusOutlined />} onClick={() => { planForm.resetFields(); planForm.setFieldsValue({ period: currentQuarter(), planned_unavailable_days: 0, bau_reserve_days: 0, risk_buffer_days: 0 }); setPlanModal(true); }}>{t('platform.newPlan')}</Button>
        : null;

  return (
    <Card title={t(titleKey)} extra={createButton}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Alert type="info" showIcon message={t('platform.subtitle')} />
        <Space wrap>
          {pane !== 'capacity' && <Input.Search allowClear value={q} onChange={(event) => setQ(event.target.value)} placeholder={t('common.search')} style={{ width: 300 }} />}
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>{t('common.refresh')}</Button>
          <Typography.Text type="secondary">{`共 ${total} 条`}</Typography.Text>
        </Space>
        {pane === 'services' ? <Table<PlatformService>
          rowKey="id" tableKey="platform.services" columns={serviceColumns} dataSource={services}
          loading={loading} freezeColumns={2} requiredColumnKeys={['item_code', 'name', 'actions']}
          scroll={{ x: 'max-content' }}
          pagination={{ current: page, pageSize, total, showSizeChanger: true, pageSizeOptions: [20, 50, 100, 200], onChange: (next, size) => { setPage(next); setPageSize(size); } }}
        /> : pane === 'demands' ? <Table<PlatformDemand>
          rowKey="id" tableKey="platform.demands" columns={demandColumns} dataSource={demands}
          loading={loading} freezeColumns={2} requiredColumnKeys={['requirement_code', 'title', 'actions']}
          scroll={{ x: 'max-content' }}
          pagination={{ current: page, pageSize, total, showSizeChanger: true, pageSizeOptions: [20, 50, 100, 200], onChange: (next, size) => { setPage(next); setPageSize(size); } }}
        /> : <Table<CapacityPlan>
          rowKey="id" tableKey="platform.capacity" columns={planColumns} dataSource={plans}
          loading={loading} freezeColumns={2} requiredColumnKeys={['service_name', 'period', 'actions']}
          scroll={{ x: 'max-content' }}
          pagination={{ current: page, pageSize, total, showSizeChanger: true, pageSizeOptions: [20, 50, 100, 200], onChange: (next, size) => { setPage(next); setPageSize(size); } }}
        />}
      </Space>

      <Modal title={editingService ? t('common.edit') : t('platform.enableService')} open={serviceModal} onOk={() => void saveService()} confirmLoading={saving} onCancel={() => setServiceModal(false)} destroyOnClose>
        <Form form={serviceForm} layout="vertical" preserve={false}>
          <Form.Item name="service_item_id" label={t('platform.service')} rules={[{ required: true }]}>
            <Select disabled={!!editingService} showSearch optionFilterProp="label" options={serviceItems.map((item) => ({ value: item.id, label: `${item.item_code} ${item.name}` }))} />
          </Form.Item>
          <Form.Item name="owner_id" label={t('platform.owner')}><Select allowClear showSearch optionFilterProp="label" options={memberOptions} /></Form.Item>
          <Form.Item name="lifecycle" label={t('platform.lifecycle')} rules={[{ required: true }]}><Select options={LIFECYCLE_OPTIONS.map((value) => ({ value, label: value }))} /></Form.Item>
          {editingService && <Form.Item name="lifecycle_change_reason" label={t('platform.lifecycleReason')}><Input.TextArea rows={2} maxLength={1000} /></Form.Item>}
          <Form.Item name="value_proposition" label={t('platform.value')}><Input.TextArea rows={3} maxLength={2000} /></Form.Item>
          <Form.Item name="scope_note" label={t('platform.scope')}><Input.TextArea rows={2} maxLength={1000} /></Form.Item>
        </Form>
      </Modal>

      <Modal title={editingDemand ? t('common.edit') : t('platform.addDemand')} open={demandModal} onOk={() => void saveDemand()} confirmLoading={saving} onCancel={() => setDemandModal(false)} destroyOnClose>
        <Form form={demandForm} layout="vertical" preserve={false}>
          <Form.Item name="requirement_id" label={t('platform.requirement')} rules={[{ required: true }]}>
            <Select disabled={!!editingDemand} showSearch optionFilterProp="label" options={requirements.map((item) => ({ value: item.id, label: `${item.requirement_code} ${item.title}` }))} />
          </Form.Item>
          <Form.Item name="service_item_id" label={t('platform.service')} rules={[{ required: true }]}><Select showSearch optionFilterProp="label" options={platformServiceOptions} /></Form.Item>
          <Form.Item name="business_domain_id" label={t('platform.domain')} rules={[{ required: true }]}><Select disabled options={domainOptions} /></Form.Item>
          <Form.Item name="demand_class" label={t('platform.demandClass')} rules={[{ required: true }]}><Select options={DEMAND_CLASS_OPTIONS.map((value) => ({ value, label: value }))} /></Form.Item>
          <Form.Item name="expected_outcome" label={t('platform.expectedOutcome')} rules={[{ required: true, min: 2 }]}><Input.TextArea rows={3} maxLength={4000} /></Form.Item>
          <Form.Item name="target_quarter" label={t('platform.targetQuarter')} rules={[{ required: true }]}><Select options={quarterOptions()} /></Form.Item>
          <Form.Item name="capacity_class" label={t('platform.capacityClass')} rules={[{ required: true }]}><Select options={CAPACITY_CLASS_OPTIONS.map((value) => ({ value, label: value }))} /></Form.Item>
        </Form>
      </Modal>

      <Modal title={t('platform.newPlan')} open={planModal} onOk={() => void savePlan()} confirmLoading={saving} onCancel={() => setPlanModal(false)} destroyOnClose>
        <Form form={planForm} layout="vertical" preserve={false}>
          <Form.Item name="service_item_id" label={t('platform.service')} rules={[{ required: true }]}><Select showSearch optionFilterProp="label" options={platformServiceOptions} /></Form.Item>
          <Form.Item name="period" label={t('platform.period')} rules={[{ required: true }]}><Select options={quarterOptions()} /></Form.Item>
          <Form.Item name="gross_days" label={t('platform.grossDays')} rules={[{ required: true }]}><InputNumber min={0} precision={2} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="planned_unavailable_days" label={t('platform.unavailableDays')}><InputNumber min={0} precision={2} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="bau_reserve_days" label={t('platform.bauDays')}><InputNumber min={0} precision={2} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="risk_buffer_days" label={t('platform.riskDays')}><InputNumber min={0} precision={2} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="notes" label={t('common.remark')}><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>

      <Drawer title={t('platform.detail')} width={860} open={!!selectedPlan} onClose={() => setSelectedPlan(undefined)}>
        {selectedPlan && <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label={t('platform.service')}>{selectedPlan.service_name}</Descriptions.Item>
            <Descriptions.Item label={t('platform.period')}>{selectedPlan.period} · v{selectedPlan.version}</Descriptions.Item>
            <Descriptions.Item label={t('common.status')}><Tag color={STATUS_COLOR[selectedPlan.status]}>{selectedPlan.status}</Tag></Descriptions.Item>
            <Descriptions.Item label={t('platform.netDays')}>{selectedPlan.net_days}</Descriptions.Item>
            <Descriptions.Item label={t('platform.committedDays')}>{selectedPlan.committed_days}</Descriptions.Item>
            <Descriptions.Item label={t('platform.remainingDays')}>{selectedPlan.remaining_days}</Descriptions.Item>
            <Descriptions.Item label={t('platform.utilization')} span={2}>
              <Progress percent={Number(selectedPlan.utilization_percent || 0)} status={Number(selectedPlan.utilization_percent || 0) > 100 ? 'exception' : 'normal'} />
            </Descriptions.Item>
            {selectedPlan.approval_reason && <Descriptions.Item label={t('platform.approvalReason')} span={2}>{selectedPlan.approval_reason}</Descriptions.Item>}
          </Descriptions>
          <Space wrap>
            {selectedPlan.status === 'draft' && canCapacityCreate && <Button icon={<PlusOutlined />} onClick={() => { commitmentForm.resetFields(); commitmentForm.setFieldsValue({ subject_type: 'requirement', commitment_type: 'demand', lifecycle_stage: 'demand', investment_intent: 'grow', status: 'planned', allow_overcommit: false }); setCommitmentModal(true); }}>{t('platform.addCommitment')}</Button>}
            {selectedPlan.status === 'draft' && canCapacityEdit && <Button type="primary" icon={<SendOutlined />} onClick={() => void submitPlan(selectedPlan)}>{t('platform.submitReview')}</Button>}
            {selectedPlan.status === 'review' && canApproveCapacity && <Button type="primary" icon={<CheckOutlined />} onClick={() => { approvalForm.resetFields(); setApprovalModal(true); }}>{t('platform.approvePlan')}</Button>}
            {['approved', 'superseded'].includes(selectedPlan.status) && canCapacityEdit && <Button icon={<BranchesOutlined />} onClick={() => { revisionForm.setFieldsValue({ service_item_id: selectedPlan.service_item_id, period: selectedPlan.period, gross_days: selectedPlan.gross_days, planned_unavailable_days: selectedPlan.planned_unavailable_days, bau_reserve_days: selectedPlan.bau_reserve_days, risk_buffer_days: selectedPlan.risk_buffer_days, notes: selectedPlan.notes }); setRevisionModal(true); }}>{t('platform.revisePlan')}</Button>}
          </Space>
          <Typography.Title level={5}>{t('platform.addCommitment')}</Typography.Title>
          <Table<CapacityCommitment>
            rowKey="id" tableKey="platform.commitments" dataSource={selectedPlan.commitments ?? []}
            columns={[
              { title: t('platform.commitmentTitle'), dataIndex: 'title', fixed: 'left' },
              { title: t('platform.commitmentType'), dataIndex: 'commitment_type', fixed: 'left' },
              { title: t('platform.capacityDays'), dataIndex: 'capacity_days' },
              { title: t('platform.lifecycleStage'), dataIndex: 'lifecycle_stage' },
              { title: t('platform.investmentIntent'), dataIndex: 'investment_intent' },
              { title: t('platform.owner'), dataIndex: 'owner_name', render: (value) => value || '-' },
              { title: t('common.status'), dataIndex: 'status' },
              { title: t('platform.overcommitReason'), dataIndex: 'over_capacity_reason', render: (value) => value || '-' },
            ]}
            freezeColumns={2} scroll={{ x: 'max-content' }} pagination={false}
          />
        </Space>}
      </Drawer>

      <Modal title={t('platform.addCommitment')} open={commitmentModal} onOk={() => void saveCommitment()} confirmLoading={saving} onCancel={() => setCommitmentModal(false)} destroyOnClose>
        <Form form={commitmentForm} layout="vertical" preserve={false}>
          <Form.Item name="subject_type" label={t('platform.subjectType')} rules={[{ required: true }]}><Select options={['requirement', 'roadmap', 'reliability', 'enablement'].map((value) => ({ value, label: value }))} /></Form.Item>
          <Form.Item noStyle shouldUpdate={(before, after) => before.subject_type !== after.subject_type}>{({ getFieldValue }) => getFieldValue('subject_type') === 'requirement' && <Form.Item name="subject_id" label={t('platform.requirement')} rules={[{ required: true }]}><Select showSearch optionFilterProp="label" options={demands.filter((item) => item.service_item_id === selectedPlan?.service_item_id).map((item) => ({ value: item.requirement_id, label: `${item.requirement_code} ${item.title}` }))} /></Form.Item>}</Form.Item>
          <Form.Item name="title" label={t('platform.commitmentTitle')} rules={[{ required: true }]}><Input maxLength={200} /></Form.Item>
          <Form.Item name="commitment_type" label={t('platform.commitmentType')} rules={[{ required: true }]}><Select options={['demand', 'roadmap', 'reliability', 'enablement'].map((value) => ({ value, label: value }))} /></Form.Item>
          <Form.Item name="capacity_days" label={t('platform.capacityDays')} rules={[{ required: true }]}><InputNumber min={0.01} precision={2} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="lifecycle_stage" label={t('platform.lifecycleStage')} rules={[{ required: true }]}><Select options={['demand', 'build', 'run'].map((value) => ({ value, label: value }))} /></Form.Item>
          <Form.Item name="investment_intent" label={t('platform.investmentIntent')} rules={[{ required: true }]}><Select options={['run', 'grow', 'transform'].map((value) => ({ value, label: value }))} /></Form.Item>
          <Form.Item name="owner_id" label={t('platform.owner')}><Select allowClear showSearch optionFilterProp="label" options={memberOptions} /></Form.Item>
          {canOverrideCapacity && <Form.Item name="allow_overcommit" label={t('platform.allowOvercommit')} valuePropName="checked"><Switch /></Form.Item>}
          {canOverrideCapacity && allowOvercommit && <Form.Item name="over_capacity_reason" label={t('platform.overcommitReason')} rules={[{ required: true, min: 5 }]}><Input.TextArea rows={2} maxLength={1000} /></Form.Item>}
        </Form>
      </Modal>

      <Modal title={t('platform.approvePlan')} open={approvalModal} onOk={() => void approvePlan()} confirmLoading={saving} onCancel={() => setApprovalModal(false)} destroyOnClose>
        <Form form={approvalForm} layout="vertical" preserve={false}><Form.Item name="reason" label={t('platform.approvalReason')} rules={[{ required: true, min: 2 }]}><Input.TextArea rows={3} maxLength={1000} /></Form.Item></Form>
      </Modal>

      <Modal title={t('platform.revisePlan')} open={revisionModal} onOk={() => void saveRevision()} confirmLoading={saving} onCancel={() => setRevisionModal(false)} destroyOnClose>
        <Form form={revisionForm} layout="vertical" preserve={false}>
          <Form.Item name="service_item_id" hidden><Input /></Form.Item><Form.Item name="period" hidden><Input /></Form.Item>
          <Form.Item name="gross_days" label={t('platform.grossDays')} rules={[{ required: true }]}><InputNumber min={0} precision={2} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="planned_unavailable_days" label={t('platform.unavailableDays')}><InputNumber min={0} precision={2} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="bau_reserve_days" label={t('platform.bauDays')}><InputNumber min={0} precision={2} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="risk_buffer_days" label={t('platform.riskDays')}><InputNumber min={0} precision={2} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="revision_reason" label={t('platform.revisionReason')} rules={[{ required: true, min: 2 }]}><Input.TextArea rows={3} maxLength={1000} /></Form.Item>
          <Form.Item name="notes" label={t('common.remark')}><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
