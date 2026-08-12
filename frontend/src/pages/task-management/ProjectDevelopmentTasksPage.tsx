import { useCallback, useEffect, useMemo, useState } from 'react';
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
import type {
  Member,
  ProjectDevelopmentTaskRow,
  ProjectDevelopmentTaskStatus,
  TicketPriority,
} from '../../api/types';
import { PRIORITY_COLORS } from '../../api/types';
import { useT } from '../../i18n';

interface ProjectRef { id: string; project_code: string; name: string; status: string }
interface WbsRef { id: string; wbs_code: string; name: string }
interface ProjectTaskForm {
  project_id: string;
  wbs_task_id?: string;
  title: string;
  description: string;
  acceptance_criteria?: string;
  task_type: string;
  assignee?: string;
  priority: TicketPriority;
  environment?: string;
  version?: string;
  plan_start?: Dayjs;
  plan_date?: Dayjs;
  plan_effort?: number;
  actual_effort?: number;
  status?: ProjectDevelopmentTaskStatus;
  completion_note?: string;
}

const STATUSES: ProjectDevelopmentTaskStatus[] = ['待处理', '进行中', '已完成'];

export default function ProjectDevelopmentTasksPage() {
  const t = useT();
  const [rows, setRows] = useState<ProjectDevelopmentTaskRow[]>([]);
  const [projects, setProjects] = useState<ProjectRef[]>([]);
  const [wbsRows, setWbsRows] = useState<WbsRef[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string>();
  const [mineOnly, setMineOnly] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<ProjectDevelopmentTaskRow | null>(null);
  const [detail, setDetail] = useState<ProjectDevelopmentTaskRow | null>(null);
  const [progressOpen, setProgressOpen] = useState(false);
  const [form] = Form.useForm<ProjectTaskForm>();
  const [progressForm] = Form.useForm<{ progress_percent?: number; comment: string }>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.getList<ProjectDevelopmentTaskRow>('/task-management/project-tasks', {
        status: status || undefined,
        scope: mineOnly ? 'mine' : undefined,
      });
      setRows(result.items);
    } finally {
      setLoading(false);
    }
  }, [mineOnly, status]);

  useEffect(() => { void load(); }, [load]);

  const loadReferences = async () => {
    const [projectResult, memberResult] = await Promise.all([
      api.getList<ProjectRef>('/task-management/reference/projects'),
      api.getList<Member>('/members', { page: 1, page_size: 2000, scope: 'it' }),
    ]);
    setProjects(projectResult.items);
    setMembers(memberResult.items);
  };

  const loadWbs = async (projectId?: string) => {
    if (!projectId) {
      setWbsRows([]);
      form.setFieldValue('wbs_task_id', undefined);
      return;
    }
    const result = await api.getList<WbsRef>(`/task-management/reference/projects/${projectId}/wbs`);
    setWbsRows(result.items);
  };

  const openCreate = async () => {
    form.resetFields();
    form.setFieldsValue({ priority: 'P3', task_type: '开发', status: '待处理' });
    setEditing(null);
    setFormOpen(true);
    await loadReferences();
    setWbsRows([]);
  };

  const openEdit = async (row: ProjectDevelopmentTaskRow) => {
    setEditing(row);
    setFormOpen(true);
    await loadReferences();
    await loadWbs(row.project_id);
    form.setFieldsValue({
      project_id: row.project_id,
      wbs_task_id: row.wbs_task_id || undefined,
      title: row.title,
      description: row.description,
      acceptance_criteria: row.acceptance_criteria || undefined,
      task_type: row.task_type,
      assignee: row.assignee || undefined,
      priority: row.priority,
      environment: row.environment || undefined,
      version: row.version || undefined,
      plan_start: row.plan_start ? dayjs(row.plan_start) : undefined,
      plan_date: row.plan_date ? dayjs(row.plan_date) : undefined,
      plan_effort: row.plan_effort ?? undefined,
      actual_effort: row.actual_effort ?? undefined,
      status: row.status,
      completion_note: row.completion_note || undefined,
    });
  };

  const submit = async () => {
    const values = await form.validateFields();
    const payload = {
      ...values,
      wbs_task_id: values.wbs_task_id || null,
      plan_start: values.plan_start?.format('YYYY-MM-DD') || null,
      plan_date: values.plan_date?.format('YYYY-MM-DD') || null,
    };
    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/task-management/project-tasks/${editing.id}`, payload);
        message.success(t('task.updated'));
      } else {
        await api.post('/task-management/project-tasks', payload);
        message.success(t('task.created'));
      }
      setFormOpen(false);
      setEditing(null);
      await load();
    } finally {
      setSaving(false);
    }
  };

  const openDetail = async (row: ProjectDevelopmentTaskRow) => {
    setDetail(await api.get<ProjectDevelopmentTaskRow>(`/task-management/project-tasks/${row.id}`));
  };

  const submitProgress = async () => {
    if (!detail) return;
    const values = await progressForm.validateFields();
    setSaving(true);
    try {
      setDetail(await api.post<ProjectDevelopmentTaskRow>(`/task-management/project-tasks/${detail.id}/progress`, values));
      message.success(t('task.progress.saved'));
      setProgressOpen(false);
      progressForm.resetFields();
      await load();
    } finally {
      setSaving(false);
    }
  };

  const remove = (row: ProjectDevelopmentTaskRow) => Modal.confirm({
    title: t('task.project.deleteConfirm'),
    okText: t('common.delete'),
    okButtonProps: { danger: true },
    cancelText: t('common.cancel'),
    onOk: async () => {
      await api.delete(`/task-management/project-tasks/${row.id}`);
      message.success(t('common.deleted'));
      await load();
    },
  });

  const columns: ColumnsType<ProjectDevelopmentTaskRow> = useMemo(() => [
    { title: t('task.code'), dataIndex: 'task_code', width: 140, render: (value, row) => <Button type="link" size="small" style={{ padding: 0 }} onClick={() => void openDetail(row)}>{value}</Button> },
    { title: t('task.title'), dataIndex: 'title', width: 240, ellipsis: true },
    { title: t('task.registrar'), dataIndex: 'registrar_name', width: 110, render: (value) => value || '-' },
    { title: t('task.project.project'), key: 'project', width: 220, render: (_, row) => `${row.project_code || ''} ${row.project_name || ''}`.trim() || '-' },
    { title: t('task.project.wbs'), key: 'wbs', width: 200, render: (_, row) => row.wbs_task_id ? `${row.wbs_code || ''} ${row.wbs_name || ''}`.trim() : '-' },
    { title: t('task.assignee'), dataIndex: 'assignee_name', width: 110, render: (value) => value || '-' },
    { title: t('task.priority'), dataIndex: 'priority', width: 80, render: (value: TicketPriority) => <Tag color={PRIORITY_COLORS[value]}>{value}</Tag> },
    { title: t('common.status'), dataIndex: 'status', width: 100, render: (value) => <Tag>{value}</Tag> },
    { title: t('task.planDate'), dataIndex: 'plan_date', width: 115, render: (value) => value || '-' },
    { title: t('task.progress.latest'), dataIndex: 'latest_progress', width: 220, ellipsis: true, render: (value: ProjectDevelopmentTaskRow['latest_progress']) => value?.comment || '-' },
    {
      title: t('common.actions'), key: 'actions', width: 150, fixed: 'right',
      render: (_, row) => <Space size={0}>
        <Button type="link" size="small" onClick={() => void openDetail(row)}>{t('common.detail')}</Button>
        {row.capabilities.edit && <Button type="link" size="small" onClick={() => void openEdit(row)}>{t('common.edit')}</Button>}
        {row.capabilities.delete && <Button type="link" size="small" danger onClick={() => remove(row)}>{t('common.delete')}</Button>}
      </Space>,
    },
  ], [t]);

  return <div>
    <Space wrap style={{ marginBottom: 16 }}>
      <Select allowClear style={{ width: 140 }} placeholder={t('task.filter.status')} value={status} onChange={setStatus} options={STATUSES.map((value) => ({ value, label: value }))} />
      <span>{t('task.filter.onlyMine')} <Switch checked={mineOnly} onChange={setMineOnly} /></span>
      <Button icon={<ReloadOutlined />} onClick={() => void load()}>{t('common.refresh')}</Button>
      <Button type="primary" icon={<PlusOutlined />} onClick={() => void openCreate()}>{t('task.register')}</Button>
    </Space>
    <Table<ProjectDevelopmentTaskRow>
      rowKey="id" loading={loading} columns={columns} dataSource={rows}
      standardToolbar={{ exportFileName: '项目开发任务', searchPlaceholder: t('task.project.search') }}
      sticky scroll={{ x: 1500 }} pagination={false}
      locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('task.project.empty')} /> }}
    />

    <Modal title={editing ? t('task.project.edit') : t('task.project.register')} open={formOpen} onOk={() => void submit()} confirmLoading={saving} onCancel={() => setFormOpen(false)} width={760} destroyOnClose>
      <Form form={form} layout="vertical" preserve={false}>
        <Space wrap size={16} align="start">
          <Form.Item name="project_id" label={t('task.project.project')} rules={[{ required: true, message: t('task.project.projectRequired') }]}>
            <Select showSearch optionFilterProp="label" style={{ width: 300 }} options={projects.map((row) => ({ value: row.id, label: `${row.project_code} ${row.name}` }))} onChange={(value) => void loadWbs(value)} />
          </Form.Item>
          <Form.Item name="wbs_task_id" label={t('task.project.wbs')} extra={t('task.project.wbsOptional')}>
            <Select allowClear showSearch optionFilterProp="label" style={{ width: 300 }} options={wbsRows.map((row) => ({ value: row.id, label: `${row.wbs_code} ${row.name}` }))} />
          </Form.Item>
        </Space>
        <Form.Item name="title" label={t('task.title')} rules={[{ required: true, message: t('task.titleRequired') }]}><Input maxLength={200} /></Form.Item>
        <Form.Item name="description" label={t('task.description')} rules={[{ required: true, message: t('task.descriptionRequired') }]}><Input.TextArea rows={3} maxLength={2000} /></Form.Item>
        <Form.Item name="acceptance_criteria" label={t('task.project.acceptance')}><Input.TextArea rows={2} maxLength={2000} /></Form.Item>
        <Space wrap size={16} align="start">
          <Form.Item name="task_type" label={t('task.taskType')}><Select style={{ width: 120 }} options={['开发', '测试', '发布', '其他'].map((value) => ({ value, label: value }))} /></Form.Item>
          <Form.Item name="assignee" label={t('task.assignee')}><Select allowClear showSearch optionFilterProp="label" style={{ width: 160 }} options={members.map((row) => ({ value: row.id, label: row.name }))} /></Form.Item>
          <Form.Item name="priority" label={t('task.priority')}><Select style={{ width: 90 }} options={['P1', 'P2', 'P3', 'P4'].map((value) => ({ value, label: value }))} /></Form.Item>
          {editing && <Form.Item name="status" label={t('common.status')}><Select style={{ width: 110 }} options={STATUSES.map((value) => ({ value, label: value }))} /></Form.Item>}
        </Space>
        <Space wrap size={16} align="start">
          <Form.Item name="environment" label={t('task.project.environment')}><Input style={{ width: 150 }} /></Form.Item>
          <Form.Item name="version" label={t('task.project.version')}><Input style={{ width: 150 }} /></Form.Item>
          <Form.Item name="plan_start" label={t('task.planStart')}><DatePicker /></Form.Item>
          <Form.Item name="plan_date" label={t('task.planDate')}><DatePicker /></Form.Item>
          <Form.Item name="plan_effort" label={t('task.planEffort')}><InputNumber min={0} precision={1} /></Form.Item>
          {editing && <Form.Item name="actual_effort" label={t('task.actualEffort')}><InputNumber min={0} precision={1} /></Form.Item>}
        </Space>
        {editing && <Form.Item name="completion_note" label={t('task.project.completion')}><Input.TextArea rows={2} /></Form.Item>}
      </Form>
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
        <Timeline style={{ marginTop: 18 }} items={detail.progress_entries.map((entry) => ({
          children: <div>
            <Space wrap>
              <Typography.Text strong>{entry.author_name || '-'}</Typography.Text>
              <Tag>{entry.status_snapshot}</Tag>
              {entry.progress_percent != null && <Progress percent={entry.progress_percent} size="small" style={{ width: 160 }} />}
              <Typography.Text type="secondary">{dayjs(entry.created_at).format('YYYY-MM-DD HH:mm')}</Typography.Text>
            </Space>
            <div>{entry.comment}</div>
          </div>,
        }))} />
        {detail.progress_entries.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('task.progress.empty')} />}
      </>}
    </Modal>

    <Modal title={t('task.progress.add')} open={progressOpen} onOk={() => void submitProgress()} confirmLoading={saving} onCancel={() => setProgressOpen(false)} destroyOnClose>
      <Form form={progressForm} layout="vertical">
        <Form.Item name="progress_percent" label={t('task.progress.percent')}><InputNumber min={0} max={100} precision={0} addonAfter="%" style={{ width: 180 }} /></Form.Item>
        <Form.Item name="comment" label={t('task.progress.comment')} rules={[{ required: true, message: t('task.progress.commentRequired') }]}><Input.TextArea rows={4} maxLength={2000} /></Form.Item>
      </Form>
    </Modal>
  </div>;
}
