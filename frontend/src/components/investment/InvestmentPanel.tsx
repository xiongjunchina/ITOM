import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import { DeleteOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import dayjs, { type Dayjs } from 'dayjs';
import { api } from '../../api/client';
import type { Member } from '../../api/types';
import Table from '../SortableTable';
import { hasPermission, useAuthStore } from '../../stores/auth';
import { useLangStore } from '../../i18n/store';

type SubjectType = 'project' | 'requirement' | 'service_item' | 'ci' | 'ticket' | 'problem' | 'contract' | 'business_domain' | 'work_task' | 'shared_operations';
type EntryMode = 'budget' | 'cost' | 'worklog';

interface InvestmentSummary {
  budget_cny: string;
  committed_cost_cny: string;
  incurred_cost_cny: string;
  paid_cost_cny: string;
  effort_days: string;
  effort_cost_cny: string;
  management_total_cny: string | null;
  unclassified_labor_cny: string;
  financial_budget_execution_rate: number | null;
  quality: {
    management_total_available: boolean;
    unclassified_labor: boolean;
    worklogs_with_rate: number | null;
    worklog_count: number | null;
  };
}

interface BudgetRow {
  id: string;
  period_start: string;
  period_end: string;
  category: string;
  cost_nature: string;
  name: string;
  amount_cny: string;
  note?: string | null;
}

interface CostRow {
  id: string;
  recognition_date: string;
  amount_cny: string;
  cost_status: string;
  category: string;
  cost_nature: string;
  recurrence: string;
  activity_type?: string | null;
  supplier_snapshot?: string | null;
  note?: string | null;
}

interface WorklogRow {
  id: string;
  person_id: string;
  person_name?: string | null;
  work_date: string;
  effort_days: string;
  role_type: string;
  activity_type: string;
  standard_rate_cny_per_day?: string | null;
  note?: string | null;
}

const CATEGORY_OPTIONS = [
  'software', 'hardware', 'cloud', 'network', 'security', 'service', 'outsourcing',
  'telecom', 'facility', 'labor', 'other',
].map((value) => ({ value, label: value }));

const ACTIVITY_OPTIONS = [
  'analysis', 'design', 'development', 'testing', 'implementation', 'pm',
  'incident_response', 'service_request', 'problem_management', 'change_delivery',
  'preventive_maintenance', 'monitoring', 'security_operations', 'asset_maintenance',
  'service_improvement', 'operations_management', 'other',
].map((value) => ({ value, label: value }));

const ROLE_OPTIONS = [
  'design', 'development', 'testing', 'implementation', 'pm', 'operations', 'other',
].map((value) => ({ value, label: value }));

function cny(value?: string | null): string {
  if (value == null) return '-';
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency', currency: 'CNY', maximumFractionDigits: 2,
  }).format(Number(value));
}

export default function InvestmentPanel({
  subjectType,
  subjectId,
  lifecycleStage,
  title,
  readOnly = false,
}: {
  subjectType: SubjectType;
  subjectId?: string;
  lifecycleStage: 'demand' | 'build' | 'run';
  title?: string;
  readOnly?: boolean;
}) {
  const user = useAuthStore((state) => state.user);
  const lang = useLangStore((state) => state.lang);
  const zh = lang !== 'en';
  const canFinance = hasPermission(user, 'reports_finance', 'view');
  const canPeopleSummary = hasPermission(user, 'reports_people', 'view');
  const canWorklogView = hasPermission(user, 'investment_worklogs', 'view');
  const canCostCreate = hasPermission(user, 'investment_costs', 'create');
  const canCostDelete = hasPermission(user, 'investment_costs', 'delete');
  const canWorklogCreate = hasPermission(user, 'investment_worklogs', 'create');
  const canWorklogDelete = hasPermission(user, 'investment_worklogs', 'delete');
  const [summary, setSummary] = useState<InvestmentSummary>();
  const [budgets, setBudgets] = useState<BudgetRow[]>([]);
  const [costs, setCosts] = useState<CostRow[]>([]);
  const [worklogs, setWorklogs] = useState<WorklogRow[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<EntryMode>();
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const subjectParams = useMemo(() => ({
    subject_type: subjectType,
    ...(subjectId ? { subject_id: subjectId } : {}),
  }), [subjectId, subjectType]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const tasks: Promise<void>[] = [];
      if (canFinance || canPeopleSummary) {
        tasks.push(api.get<InvestmentSummary>('/investments/summary', {
          ...subjectParams, lifecycle_stage: lifecycleStage,
        }).then(setSummary));
      }
      if (canFinance) {
        tasks.push(api.getList<BudgetRow>('/investments/budgets', { ...subjectParams, page_size: 200 }).then((result) => setBudgets(result.items)));
        tasks.push(api.getList<CostRow>('/investments/costs', { ...subjectParams, page_size: 200 }).then((result) => setCosts(result.items)));
      }
      if (canWorklogView) {
        tasks.push(api.getList<WorklogRow>('/investments/worklogs', { ...subjectParams, page_size: 200 }).then((result) => setWorklogs(result.items)));
      }
      await Promise.all(tasks);
    } finally {
      setLoading(false);
    }
  }, [canFinance, canPeopleSummary, canWorklogView, lifecycleStage, subjectParams]);

  useEffect(() => {
    void load();
  }, [load]);

  const open = (nextMode: EntryMode) => {
    setMode(nextMode);
    form.resetFields();
    if (nextMode === 'budget') {
      form.setFieldsValue({ period: [dayjs().startOf('year'), dayjs().endOf('year')], category: 'other', cost_nature: 'opex' });
    } else if (nextMode === 'cost') {
      form.setFieldsValue({ recognition_date: dayjs(), category: 'other', cost_status: 'incurred', cost_nature: 'opex', recurrence: 'one_time' });
    } else {
      form.setFieldsValue({ person_id: user?.person_id, work_date: dayjs(), effort_days: 1, role_type: lifecycleStage === 'run' ? 'operations' : 'implementation', activity_type: lifecycleStage === 'run' ? 'service_request' : 'implementation' });
      if (!members.length) {
        void api.getList<Member>('/members', { page: 1, page_size: 2000, scope: 'it' })
          .then((result) => setMembers(result.items))
          .catch(() => undefined);
      }
    }
  };

  const save = async () => {
    if (!mode) return;
    const values = await form.validateFields();
    setSaving(true);
    try {
      const base = { ...subjectParams, lifecycle_stage: lifecycleStage };
      if (mode === 'budget') {
        const period = values.period as [Dayjs, Dayjs];
        await api.post('/investments/budgets', {
          ...base, ...values, period: undefined,
          period_start: period[0].format('YYYY-MM-DD'), period_end: period[1].format('YYYY-MM-DD'),
        });
      } else if (mode === 'cost') {
        await api.post('/investments/costs', {
          ...base, ...values, recognition_date: (values.recognition_date as Dayjs).format('YYYY-MM-DD'),
        });
      } else {
        await api.post('/investments/worklogs', {
          ...base, ...values, work_date: (values.work_date as Dayjs).format('YYYY-MM-DD'),
        });
      }
      message.success(zh ? '投入记录已保存' : 'Investment entry saved');
      setMode(undefined);
      await load();
    } finally {
      setSaving(false);
    }
  };

  const remove = async (entryMode: EntryMode, id: string) => {
    await api.delete(`/investments/${entryMode === 'budget' ? 'budgets' : entryMode === 'cost' ? 'costs' : 'worklogs'}/${id}`);
    message.success(zh ? '投入记录已删除' : 'Investment entry deleted');
    await load();
  };

  const budgetColumns = [
    { title: zh ? '周期' : 'Period', key: 'period', render: (_: unknown, row: BudgetRow) => `${row.period_start} ~ ${row.period_end}` },
    { title: zh ? '分类' : 'Category', dataIndex: 'category' },
    { title: zh ? '预算项' : 'Budget item', dataIndex: 'name' },
    { title: zh ? '性质' : 'Nature', dataIndex: 'cost_nature' },
    { title: zh ? '金额' : 'Amount', dataIndex: 'amount_cny', render: cny },
    ...(canCostDelete ? [{ title: zh ? '操作' : 'Action', key: 'action', render: (_: unknown, row: BudgetRow) => <Button type="text" danger icon={<DeleteOutlined />} onClick={() => void remove('budget', row.id)} /> }] : []),
  ];
  const costColumns = [
    { title: zh ? '确认日期' : 'Recognition date', dataIndex: 'recognition_date' },
    { title: zh ? '分类' : 'Category', dataIndex: 'category' },
    { title: zh ? '状态' : 'Status', dataIndex: 'cost_status', render: (value: string) => <Tag>{value}</Tag> },
    { title: zh ? '性质' : 'Nature', dataIndex: 'cost_nature' },
    { title: zh ? '金额' : 'Amount', dataIndex: 'amount_cny', render: cny },
    { title: zh ? '活动' : 'Activity', dataIndex: 'activity_type', render: (value?: string) => value || '-' },
    ...(canCostDelete ? [{ title: zh ? '操作' : 'Action', key: 'action', render: (_: unknown, row: CostRow) => <Button type="text" danger icon={<DeleteOutlined />} onClick={() => void remove('cost', row.id)} /> }] : []),
  ];
  const worklogColumns = [
    { title: zh ? '日期' : 'Date', dataIndex: 'work_date' },
    { title: zh ? '人员' : 'Person', dataIndex: 'person_name', render: (value: string | null, row: WorklogRow) => value || row.person_id },
    { title: zh ? '角色' : 'Role', dataIndex: 'role_type' },
    { title: zh ? '活动' : 'Activity', dataIndex: 'activity_type' },
    { title: zh ? '实际人天' : 'Effort days', dataIndex: 'effort_days' },
    { title: zh ? '标准日费率' : 'Standard rate/day', dataIndex: 'standard_rate_cny_per_day', render: cny },
    ...(canWorklogDelete ? [{ title: zh ? '操作' : 'Action', key: 'action', render: (_: unknown, row: WorklogRow) => <Button type="text" danger icon={<DeleteOutlined />} onClick={() => void remove('worklog', row.id)} /> }] : []),
  ];

  if (!canFinance && !canWorklogView && !canPeopleSummary) return null;
  return (
    <Card
      size="small"
      title={title ?? (zh ? '投入与资源台账' : 'Investment and Resource Ledger')}
      extra={<Space>
        {canCostCreate && !readOnly && <Button size="small" icon={<PlusOutlined />} onClick={() => open('budget')}>{zh ? '预算' : 'Budget'}</Button>}
        {canCostCreate && !readOnly && <Button size="small" icon={<PlusOutlined />} onClick={() => open('cost')}>{zh ? '费用' : 'Cost'}</Button>}
        {canWorklogCreate && !readOnly && <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => open('worklog')}>{zh ? '实际工时' : 'Worklog'}</Button>}
        <Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={() => void load()} />
      </Space>}
    >
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {summary && <>
          <Row gutter={[12, 12]}>
            {canFinance && <Col xs={12} md={6}><Statistic title={zh ? '预算' : 'Budget'} value={cny(summary.budget_cny)} /></Col>}
            {canFinance && <Col xs={12} md={6}><Statistic title={zh ? '已发生费用' : 'Incurred cost'} value={cny(summary.incurred_cost_cny)} /></Col>}
            {canPeopleSummary && <Col xs={12} md={6}><Statistic title={zh ? '实际人天' : 'Effort days'} value={summary.effort_days} /></Col>}
            {canFinance && <Col xs={12} md={6}><Statistic title={zh ? '管理总投入' : 'Management total'} value={summary.management_total_cny == null ? '-' : cny(summary.management_total_cny)} /></Col>}
          </Row>
          {summary.quality.unclassified_labor && (
            <Alert type="warning" showIcon message={zh
              ? '存在未分类的人力费用，为避免与工时估值重复计算，管理总投入暂不出数。'
              : 'Unclassified labor cost exists. Management total is suppressed to prevent double counting with worklog valuation.'} />
          )}
        </>}
        <Tabs items={[
          ...(canFinance ? [
            { key: 'budget', label: zh ? `预算（${budgets.length}）` : `Budgets (${budgets.length})`, children: <Table rowKey="id" columns={budgetColumns} dataSource={budgets} pagination={false} scroll={{ x: 'max-content' }} /> },
            { key: 'cost', label: zh ? `费用（${costs.length}）` : `Costs (${costs.length})`, children: <Table rowKey="id" columns={costColumns} dataSource={costs} pagination={false} scroll={{ x: 'max-content' }} /> },
          ] : []),
          ...(canWorklogView ? [{ key: 'worklog', label: zh ? `实际工时（${worklogs.length}）` : `Worklogs (${worklogs.length})`, children: <Table rowKey="id" columns={worklogColumns} dataSource={worklogs} pagination={false} scroll={{ x: 'max-content' }} /> }] : []),
        ]} />
      </Space>

      <Modal
        title={mode === 'budget' ? (zh ? '登记预算' : 'Add budget') : mode === 'cost' ? (zh ? '登记费用' : 'Add cost') : (zh ? '登记实际工时' : 'Add worklog')}
        open={!!mode}
        onOk={() => void save()}
        confirmLoading={saving}
        onCancel={() => setMode(undefined)}
        destroyOnClose
      >
        <Form form={form} layout="vertical" preserve={false}>
          {mode === 'budget' && <>
            <Form.Item name="period" label={zh ? '预算周期' : 'Budget period'} rules={[{ required: true }]}><DatePicker.RangePicker style={{ width: '100%' }} /></Form.Item>
            <Form.Item name="name" label={zh ? '预算项名称' : 'Budget item'} rules={[{ required: true }]}><Input maxLength={128} /></Form.Item>
            <Form.Item name="category" label={zh ? '费用分类' : 'Category'} rules={[{ required: true }]}><Select options={CATEGORY_OPTIONS} /></Form.Item>
            <Form.Item name="cost_nature" label={zh ? '资本/运营性质' : 'CAPEX/OPEX'}><Select options={[{ value: 'capex', label: 'CAPEX' }, { value: 'opex', label: 'OPEX' }]} /></Form.Item>
            <Form.Item name="amount_cny" label={zh ? '预算金额（元）' : 'Budget amount (CNY)'} rules={[{ required: true }]}><InputNumber min={0.01} precision={2} style={{ width: '100%' }} /></Form.Item>
          </>}
          {mode === 'cost' && <>
            <Form.Item name="recognition_date" label={zh ? '确认日期' : 'Recognition date'} rules={[{ required: true }]}><DatePicker disabledDate={(current) => current.isAfter(dayjs(), 'day')} style={{ width: '100%' }} /></Form.Item>
            <Form.Item name="amount_cny" label={zh ? '金额（元）' : 'Amount (CNY)'} rules={[{ required: true }]}><InputNumber min={0.01} precision={2} style={{ width: '100%' }} /></Form.Item>
            <Form.Item name="cost_status" label={zh ? '费用状态' : 'Cost status'}><Select options={[{ value: 'committed', label: zh ? '已承诺' : 'Committed' }, { value: 'incurred', label: zh ? '已发生' : 'Incurred' }, { value: 'paid', label: zh ? '已支付' : 'Paid' }]} /></Form.Item>
            <Form.Item name="category" label={zh ? '费用分类' : 'Category'}><Select options={CATEGORY_OPTIONS} /></Form.Item>
            <Form.Item name="cost_nature" label={zh ? '资本/运营性质' : 'CAPEX/OPEX'}><Select options={[{ value: 'capex', label: 'CAPEX' }, { value: 'opex', label: 'OPEX' }]} /></Form.Item>
            <Form.Item name="recurrence" label={zh ? '发生方式' : 'Recurrence'}><Select options={[{ value: 'one_time', label: zh ? '一次性' : 'One-time' }, { value: 'recurring', label: zh ? '持续性' : 'Recurring' }]} /></Form.Item>
            <Form.Item name="activity_type" label={zh ? '活动类型' : 'Activity'}><Select allowClear options={ACTIVITY_OPTIONS} /></Form.Item>
            <Form.Item name="supplier_snapshot" label={zh ? '供应商快照' : 'Supplier snapshot'}><Input maxLength={128} /></Form.Item>
          </>}
          {mode === 'worklog' && <>
            <Form.Item name="person_id" label={zh ? '投入人员' : 'Person'} rules={[{ required: true }]}><Select showSearch optionFilterProp="label" disabled={!hasPermission(user, 'investment_worklogs', 'edit')} options={members.map((row) => ({ value: row.id, label: row.name }))} /></Form.Item>
            <Form.Item name="work_date" label={zh ? '实际日期' : 'Work date'} rules={[{ required: true }]}><DatePicker disabledDate={(current) => current.isAfter(dayjs(), 'day')} style={{ width: '100%' }} /></Form.Item>
            <Form.Item name="effort_days" label={zh ? '实际人天' : 'Effort days'} rules={[{ required: true }]}><InputNumber min={0.01} max={2} precision={2} style={{ width: '100%' }} /></Form.Item>
            <Form.Item name="role_type" label={zh ? '投入角色' : 'Role'}><Select options={ROLE_OPTIONS} /></Form.Item>
            <Form.Item name="activity_type" label={zh ? '活动类型' : 'Activity'}><Select options={ACTIVITY_OPTIONS} /></Form.Item>
            <Form.Item name="standard_rate_cny_per_day" label={zh ? '标准日费率（非个人薪酬）' : 'Standard daily rate (not salary)'}><InputNumber min={0} precision={2} style={{ width: '100%' }} /></Form.Item>
          </>}
          <Form.Item name="note" label={zh ? '备注' : 'Note'}><Input.TextArea maxLength={500} rows={2} /></Form.Item>
          <Typography.Text type="secondary">
            {zh ? '实际人天按人员、日期累计校验；单日合计不能超过 2 人天。' : 'Actual effort is validated per person and date; the daily total cannot exceed 2 person-days.'}
          </Typography.Text>
        </Form>
      </Modal>
    </Card>
  );
}
