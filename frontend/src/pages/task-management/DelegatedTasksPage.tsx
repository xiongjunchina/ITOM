import { useCallback, useEffect, useState } from 'react';
import {
  Button,
  DatePicker,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Progress,
  Select,
  Space,
  Switch,
  Tag,
  Timeline,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import dayjs, { type Dayjs } from 'dayjs';
import Table from '../../components/SortableTable';
import { api } from '../../api/client';
import type { Member, TicketPriority, WorkTaskRow, WorkTaskStatus } from '../../api/types';
import { PRIORITY_COLORS } from '../../api/types';
import { useT } from '../../i18n';

const STATUSES: WorkTaskStatus[] = ['登记', '排期', '执行', '暂停', '关闭', '中止'];
const NEXT: Record<string, WorkTaskStatus[]> = {
  登记: ['排期', '中止'], 排期: ['执行', '中止'], 执行: ['暂停', '关闭', '中止'], 暂停: ['执行', '中止'], 关闭: [], 中止: [],
};

interface TaskFormValues {
  title: string;
  description: string;
  task_type: string;
  source_type: string;
  source_id?: string;
  assignee?: string;
  priority: TicketPriority;
  plan_start?: Dayjs;
  plan_date?: Dayjs;
  plan_effort?: number;
  actual_effort?: number;
  performance_bucket: string;
}

export default function DelegatedTasksPage() {
  const t = useT();
  const [rows, setRows] = useState<WorkTaskRow[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<string>();
  const [mineOnly, setMineOnly] = useState(false);
  const [editing, setEditing] = useState<WorkTaskRow | null>(null);
  const [transitioning, setTransitioning] = useState<{ row: WorkTaskRow; to: WorkTaskStatus } | null>(null);
  const [detail, setDetail] = useState<WorkTaskRow | null>(null);
  const [progressOpen, setProgressOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<TaskFormValues>();
  const [transitionForm] = Form.useForm<{ reason: string }>();
  const [progressForm] = Form.useForm<{ progress_percent?: number; comment: string }>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.getList<WorkTaskRow>('/task-management/work-tasks', {
        status: status || undefined,
        scope: mineOnly ? 'mine' : undefined,
      });
      setRows(result.items);
    } catch {
      // API client 已统一提示错误
    } finally {
      setLoading(false);
    }
  }, [mineOnly, status]);

  useEffect(() => { void load(); }, [load]);

  const loadMembers = () => {
    if (members.length === 0) {
      api.getList<Member>('/members', { page: 1, page_size: 2000, scope: 'it' }).then((result) => setMembers(result.items)).catch(() => undefined);
    }
  };

  const openCreate = () => {
    form.resetFields();
    form.setFieldsValue({ priority: 'P3', task_type: '其他', source_type: 'manual', performance_bucket: 'role_result' });
    setEditing(null);
    loadMembers();
    // null 代表新建；单独用 editingId 避免把 Modal 误认为编辑态
    setCreateOpen(true);
  };

  const [createOpen, setCreateOpen] = useState(false);

  const openEdit = (row: WorkTaskRow) => {
    form.setFieldsValue({
      title: row.title,
      description: row.description,
      task_type: row.task_type,
      source_type: row.source_type,
      source_id: row.source_id || undefined,
      assignee: row.assignee || undefined,
      priority: row.priority,
      plan_start: row.plan_start ? dayjs(row.plan_start) : undefined,
      plan_date: row.plan_date ? dayjs(row.plan_date) : undefined,
      plan_effort: row.plan_effort ?? undefined,
      actual_effort: row.actual_effort ?? undefined,
      performance_bucket: row.performance_bucket,
    });
    setEditing(row);
    setCreateOpen(false);
    loadMembers();
  };

  const submitForm = async () => {
    const values = await form.validateFields();
    const payload = {
      ...values,
      plan_start: values.plan_start?.format('YYYY-MM-DD'),
      plan_date: values.plan_date?.format('YYYY-MM-DD'),
    };
    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/task-management/work-tasks/${editing.id}`, payload);
        message.success(t('task.updated'));
      } else {
        await api.post('/task-management/work-tasks', payload);
        message.success(t('task.created'));
      }
      setCreateOpen(false);
      setEditing(null);
      await load();
    } catch {
      // API client 已统一提示错误
    } finally {
      setSaving(false);
    }
  };

  const openTransition = (row: WorkTaskRow, to: WorkTaskStatus) => {
    transitionForm.resetFields();
    setTransitioning({ row, to });
  };

  const submitTransition = async () => {
    if (!transitioning) return;
    const values = await transitionForm.validateFields();
    setSaving(true);
    try {
      await api.post(`/task-management/work-tasks/${transitioning.row.id}/transition`, { to: transitioning.to, reason: values.reason || '' });
      message.success(t('task.transitionDone'));
      setTransitioning(null);
      await load();
    } catch {
      // API client 已统一提示错误
    } finally {
      setSaving(false);
    }
  };

  const remove = (row: WorkTaskRow) => {
    Modal.confirm({
      title: t('task.deleteConfirm'), okText: t('common.delete'), okButtonProps: { danger: true }, cancelText: t('common.cancel'),
      onOk: async () => { await api.delete(`/task-management/work-tasks/${row.id}`); message.success(t('common.deleted')); void load(); },
    });
  };

  const openDetail = async (row: WorkTaskRow) => {
    const current = await api.get<WorkTaskRow>(`/task-management/work-tasks/${row.id}`);
    setDetail(current);
  };

  const submitProgress = async () => {
    if (!detail) return;
    const values = await progressForm.validateFields();
    setSaving(true);
    try {
      const current = await api.post<WorkTaskRow>(`/task-management/work-tasks/${detail.id}/progress`, values);
      message.success(t('task.progress.saved'));
      setDetail(current);
      setProgressOpen(false);
      progressForm.resetFields();
      await load();
    } finally {
      setSaving(false);
    }
  };

  const columns: ColumnsType<WorkTaskRow> = [
    { title: t('task.code'), dataIndex: 'task_code', width: 140, render: (value, row) => <Button type="link" size="small" style={{ padding: 0 }} onClick={() => void openDetail(row)}>{value}</Button> },
    { title: t('task.title'), dataIndex: 'title', width: 260, ellipsis: true },
    { title: t('task.taskType'), dataIndex: 'task_type', width: 110 },
    { title: t('task.assignee'), dataIndex: 'assignee_name', width: 110, render: (v) => v || '-' },
    { title: t('task.registrar'), dataIndex: 'registrar_name', width: 110, render: (v) => v || '-' },
    { title: t('task.priority'), dataIndex: 'priority', width: 90, render: (v: TicketPriority) => <Tag color={PRIORITY_COLORS[v]}>{v}</Tag> },
    { title: t('common.status'), dataIndex: 'status', width: 90, render: (v) => <Tag>{v}</Tag> },
    { title: t('task.planDate'), dataIndex: 'plan_date', width: 120, render: (v) => v || '-' },
    { title: t('task.progress.latest'), dataIndex: 'latest_progress', width: 220, ellipsis: true, render: (v: WorkTaskRow['latest_progress']) => v?.comment || '-' },
    {
      title: t('common.actions'), key: 'actions', width: 240, fixed: 'right',
      render: (_: unknown, row: WorkTaskRow) => <Space size={0} wrap>
        <Button type="link" size="small" onClick={() => void openDetail(row)}>{t('common.detail')}</Button>
        {row.capabilities.edit && <Button type="link" size="small" onClick={() => openEdit(row)}>{t('common.edit')}</Button>}
        {row.capabilities.transition && NEXT[row.status].map((next) => <Button key={next} type="link" size="small" onClick={() => openTransition(row, next)}>{next}</Button>)}
        {row.capabilities.delete && <Button type="link" size="small" danger onClick={() => remove(row)}>{t('common.delete')}</Button>}
      </Space>,
    },
  ];

  return (
    <div>
      <Space wrap style={{ marginBottom: 16 }}>
        <Select allowClear style={{ width: 140 }} placeholder={t('task.filter.status')} value={status} onChange={setStatus} options={STATUSES.map((v) => ({ value: v, label: v }))} />
        <span>{t('task.filter.onlyMine')} <Switch checked={mineOnly} onChange={setMineOnly} /></span>
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>{t('common.refresh')}</Button>
        <Button className="task-register-hitbox" type="primary" icon={<PlusOutlined />} onClick={openCreate}>{t('task.register')}</Button>
      </Space>
      <Table<WorkTaskRow>
        rowKey="id" loading={loading} columns={columns} dataSource={rows}
        standardToolbar={{ exportFileName: '委派任务', searchPlaceholder: t('task.search') }} sticky scroll={{ x: 1320 }} pagination={false}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('task.empty')} /> }}
      />

      <Modal title={editing ? t('task.edit') : t('task.register')} open={createOpen || !!editing} onOk={() => void submitForm()} confirmLoading={saving} onCancel={() => { setCreateOpen(false); setEditing(null); }} destroyOnClose width={680}>
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item name="title" label={t('task.title')} rules={[{ required: true, message: t('task.titleRequired') }]}><Input maxLength={200} /></Form.Item>
          <Form.Item name="description" label={t('task.description')} rules={[{ required: true, message: t('task.descriptionRequired') }]}><Input.TextArea rows={3} maxLength={2000} /></Form.Item>
          <Space wrap size={16}>
            <Form.Item name="task_type" label={t('task.taskType')} rules={[{ required: true }]}><Select style={{ width: 150 }} options={['技术研究', '跨团队支持', '知识分享', '系统优化', '运维执行', '其他'].map((v) => ({ value: v, label: v }))} /></Form.Item>
            <Form.Item name="source_type" label={t('task.source')}><Select style={{ width: 150 }} options={['manual', 'ticket', 'problem', 'incident'].map((v) => ({ value: v, label: t(`task.source.${v}`) }))} /></Form.Item>
            <Form.Item name="priority" label={t('task.priority')}><Select style={{ width: 100 }} options={['P1', 'P2', 'P3', 'P4'].map((v) => ({ value: v, label: v }))} /></Form.Item>
          </Space>
          <Space wrap size={16}>
            <Form.Item name="assignee" label={t('task.assignee')}><Select allowClear showSearch optionFilterProp="label" style={{ width: 180 }} options={members.map((m) => ({ value: m.id, label: m.name }))} /></Form.Item>
            <Form.Item name="plan_start" label={t('task.planStart')}><DatePicker /></Form.Item>
            <Form.Item name="plan_date" label={t('task.planDate')}><DatePicker /></Form.Item>
            <Form.Item name="plan_effort" label={t('task.planEffort')}><InputNumber min={0} precision={1} /></Form.Item>
          </Space>
          {editing && <Space wrap><Form.Item name="actual_effort" label={t('task.actualEffort')}><InputNumber min={0} precision={1} /></Form.Item><Form.Item name="performance_bucket" label={t('task.performance')}><Select style={{ width: 180 }} options={[{ value: 'role_result', label: t('task.performanceRole') }, { value: 'team_contribution', label: t('task.performanceTeam') }]} /></Form.Item></Space>}
          {!editing && <Form.Item name="performance_bucket" label={t('task.performance')}><Select style={{ width: 220 }} options={[{ value: 'role_result', label: t('task.performanceRole') }, { value: 'team_contribution', label: t('task.performanceTeam') }]} /></Form.Item>}
          <Form.Item name="source_id" label={t('task.sourceId')}><Input /></Form.Item>
        </Form>
      </Modal>

      <Modal title={`${t('task.transition')}${transitioning ? `：${transitioning.to}` : ''}`} open={!!transitioning} onOk={() => void submitTransition()} confirmLoading={saving} onCancel={() => setTransitioning(null)} destroyOnClose>
        <Form form={transitionForm} layout="vertical"><Form.Item name="reason" label={transitioning && ['暂停', '中止', '关闭'].includes(transitioning.to) ? t('task.reason') : t('common.remark')} rules={transitioning && ['暂停', '中止'].includes(transitioning.to) ? [{ required: true, min: 2, message: t('task.reasonRequired') }] : []}><Input.TextArea rows={3} /></Form.Item></Form>
      </Modal>

      <Modal title={detail ? `${detail.task_code} · ${detail.title}` : t('common.detail')} open={!!detail} footer={null} onCancel={() => setDetail(null)} width={760} destroyOnClose>
        {detail && <>
          <Space wrap style={{ marginBottom: 12 }}>
            <Tag>{detail.status}</Tag>
            <Tag color={PRIORITY_COLORS[detail.priority]}>{detail.priority}</Tag>
            {detail.capabilities.progress && <Button type="primary" onClick={() => { progressForm.resetFields(); setProgressOpen(true); }}>{t('task.progress.add')}</Button>}
          </Space>
          <Typography.Paragraph>{detail.description}</Typography.Paragraph>
          <Typography.Text strong>{t('task.progress.timeline')}</Typography.Text>
          <Timeline
            style={{ marginTop: 18 }}
            items={detail.progress_entries.map((entry) => ({
              children: <div>
                <Space wrap>
                  <Typography.Text strong>{entry.author_name || '-'}</Typography.Text>
                  <Tag>{entry.status_snapshot}</Tag>
                  {entry.progress_percent != null && <Progress percent={entry.progress_percent} size="small" style={{ width: 160 }} />}
                  <Typography.Text type="secondary">{dayjs(entry.created_at).format('YYYY-MM-DD HH:mm')}</Typography.Text>
                </Space>
                <div>{entry.comment}</div>
              </div>,
            }))}
          />
          {detail.progress_entries.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('task.progress.empty')} />}
        </>}
      </Modal>

      <Modal title={t('task.progress.add')} open={progressOpen} onOk={() => void submitProgress()} confirmLoading={saving} onCancel={() => setProgressOpen(false)} destroyOnClose>
        <Form form={progressForm} layout="vertical">
          <Form.Item name="progress_percent" label={t('task.progress.percent')}><InputNumber min={0} max={100} precision={0} addonAfter="%" style={{ width: 180 }} /></Form.Item>
          <Form.Item name="comment" label={t('task.progress.comment')} rules={[{ required: true, message: t('task.progress.commentRequired') }]}><Input.TextArea rows={4} maxLength={2000} /></Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
