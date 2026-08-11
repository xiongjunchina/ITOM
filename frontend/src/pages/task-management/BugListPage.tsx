import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Descriptions,
  Divider,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table as AntTable,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { UploadFile } from 'antd/es/upload/interface';
import { DownloadOutlined, PlusOutlined, ReloadOutlined, UploadOutlined } from '@ant-design/icons';
import { type Dayjs } from 'dayjs';
import Table from '../../components/SortableTable';
import { api } from '../../api/client';
import type { AttachmentItem, BugFixTaskRow, BugRow, CiRow, Member, TicketPriority } from '../../api/types';
import { PRIORITY_COLORS } from '../../api/types';
import { useT } from '../../i18n';
import { useAuthStore } from '../../stores/auth';
import { useProcessTaskView } from '../../utils/processTaskView';

const BUG_STATUS: Record<string, { label: string; color: string }> = {
  registered: { label: '待确认', color: 'gold' },
  confirmed: { label: '待生成修复任务', color: 'processing' },
  fixing: { label: '开发修复中', color: 'blue' },
  resolved: { label: '待验证关闭', color: 'purple' },
  closed: { label: '已关闭', color: 'success' },
  rejected: { label: '已驳回', color: 'error' },
};

const FIX_NEXT: Record<string, string[]> = {
  登记: ['排期'], 排期: ['执行'], 执行: ['暂停', '关闭'], 暂停: ['执行', '关闭'], 关闭: [],
};

interface BugFormValues {
  title: string;
  description: string;
  ci_id: string;
  priority: TicketPriority;
  reproduction?: string;
  expected_result?: string;
  actual_result?: string;
  environment?: string;
  evidence?: string;
}

interface ActionValues {
  reason: string;
}

interface FixTaskFormValues {
  tasks: Array<{
    name: string;
    task_type: string;
    description?: string;
    assignee: string;
    plan_start?: Dayjs;
    plan_date?: Dayjs;
    plan_effort?: number;
  }>;
}

export default function BugListPage() {
  const t = useT();
  const user = useAuthStore((state) => state.user);
  const [rows, setRows] = useState<BugRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<string>();
  const [mineOnly, setMineOnly] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [editingBug, setEditingBug] = useState<BugRow | null>(null);
  const [detail, setDetail] = useState<BugRow | null>(null);
  const [action, setAction] = useState<'reject' | 'verify-fail' | 'verify-close' | 'reopen' | null>(null);
  const [actionSaving, setActionSaving] = useState(false);
  const [fixOpen, setFixOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [bugForm] = Form.useForm<BugFormValues>();
  const [actionForm] = Form.useForm<ActionValues>();
  const [fixForm] = Form.useForm<FixTaskFormValues>();
  const [cis, setCis] = useState<CiRow[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [pendingFiles, setPendingFiles] = useState<UploadFile[]>([]);
  const [attachments, setAttachments] = useState<AttachmentItem[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.getList<BugRow>('/task-management/bugs', {
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

  const loadReferences = async () => {
    if (cis.length === 0 || members.length === 0) {
      const [ciResult, memberResult] = await Promise.all([
        cis.length === 0 ? api.getList<CiRow>('/task-management/reference/cis', { page: 1, page_size: 2000 }) : Promise.resolve({ items: cis, total: cis.length }),
        members.length === 0 ? api.getList<Member>('/members', { page: 1, page_size: 2000, scope: 'it' }) : Promise.resolve({ items: members, total: members.length }),
      ]);
      setCis(ciResult.items);
      setMembers(memberResult.items);
    }
  };

  const loadAttachments = async (bugId: string) => {
    const result = await api.getList<AttachmentItem>('/attachments', {
      entity_type: 'bug', entity_id: bugId,
    });
    setAttachments(result.items);
    return result.items;
  };

  const refreshDetail = async (bugId: string) => {
    const [next] = await Promise.all([
      api.get<BugRow>(`/task-management/bugs/${bugId}`),
      loadAttachments(bugId),
    ]);
    setDetail(next);
    void load();
  };

  const uploadEvidenceFiles = async (bugId: string, files: UploadFile[]) => {
    let uploaded = 0;
    for (const item of files) {
      const file = item.originFileObj ?? item;
      if (!(file instanceof File)) continue;
      try {
        await api.upload<AttachmentItem>(`/attachments?entity_type=bug&entity_id=${bugId}`, file);
        uploaded += 1;
      } catch {
        // 单个文件失败不回滚已登记的 Bug；用户可在详情中补传。
      }
    }
    await loadAttachments(bugId);
    return uploaded;
  };

  useProcessTaskView(detail?.process, user, detail ? () => { void refreshDetail(detail.id); } : undefined);

  const openCreate = () => {
    bugForm.resetFields();
    bugForm.setFieldValue('priority', 'P2');
    setPendingFiles([]);
    setCreateOpen(true);
    void loadReferences();
  };

  const submitCreate = async () => {
    const values = await bugForm.validateFields();
    setSaving(true);
    try {
      const created = await api.post<BugRow>('/task-management/bugs', values);
      const uploaded = created?.id && pendingFiles.length
        ? await uploadEvidenceFiles(created.id, pendingFiles)
        : 0;
      if (pendingFiles.length && uploaded < pendingFiles.length) {
        message.warning(t('task.bug.attachmentPartial', { uploaded, total: pendingFiles.length }));
      } else {
        message.success(t('task.bug.created'));
      }
      setCreateOpen(false);
      await load();
      if (created?.id) await refreshDetail(created.id);
    } catch {
      // API client 已统一提示错误
    } finally {
      setSaving(false);
    }
  };

  const openEdit = (bug: BugRow) => {
    void loadReferences();
    bugForm.setFieldsValue({
      title: bug.title,
      ci_id: bug.ci_id,
      description: bug.description,
      priority: bug.priority,
      reproduction: bug.reproduction ?? undefined,
      expected_result: bug.expected_result ?? undefined,
      actual_result: bug.actual_result ?? undefined,
      environment: bug.environment ?? undefined,
      evidence: bug.evidence ?? undefined,
    });
    setEditingBug(bug);
  };

  const submitEdit = async () => {
    if (!editingBug) return;
    const values = await bugForm.validateFields();
    setSaving(true);
    try {
      await api.patch(`/task-management/bugs/${editingBug.id}`, {
        title: values.title,
        ci_id: values.ci_id,
        description: values.description,
        priority: values.priority,
        reproduction: values.reproduction || null,
        expected_result: values.expected_result || null,
        actual_result: values.actual_result || null,
        environment: values.environment || null,
        evidence: values.evidence || null,
      });
      message.success(t('common.saved'));
      setEditingBug(null);
      await refreshDetail(editingBug.id);
    } catch {
      // API client 已统一提示错误
    } finally {
      setSaving(false);
    }
  };

  const openAction = (kind: NonNullable<typeof action>) => {
    actionForm.resetFields();
    setAction(kind);
  };

  const submitAction = async () => {
    if (!detail || !action) return;
    const values = await actionForm.validateFields();
    setActionSaving(true);
    try {
      if (action === 'reject') {
        await api.post(`/task-management/bugs/${detail.id}/reject-confirm`, { reason: values.reason });
      } else if (action === 'reopen') {
        await api.post(`/task-management/bugs/${detail.id}/reopen`, { reason: values.reason });
      } else {
        await api.post(`/task-management/bugs/${detail.id}/verify`, {
          verified: action === 'verify-close', note: values.reason,
        });
      }
      message.success(t('task.bug.actionDone'));
      setAction(null);
      await refreshDetail(detail.id);
    } catch {
      // API client 已统一提示错误
    } finally {
      setActionSaving(false);
    }
  };

  const openGenerate = () => {
    fixForm.setFieldsValue({ tasks: [{ name: '', task_type: '开发', assignee: undefined }] });
    setFixOpen(true);
    void loadReferences();
  };

  const submitGenerate = async () => {
    if (!detail) return;
    const values = await fixForm.validateFields();
    setSaving(true);
    try {
      await api.post(`/task-management/bugs/${detail.id}/fix-tasks`, {
        tasks: values.tasks.map((row) => ({
          ...row,
          plan_start: row.plan_start?.format('YYYY-MM-DD'),
          plan_date: row.plan_date?.format('YYYY-MM-DD'),
        })),
      });
      message.success(t('task.bug.fixCreated'));
      setFixOpen(false);
      await refreshDetail(detail.id);
    } catch {
      // API client 已统一提示错误
    } finally {
      setSaving(false);
    }
  };

  const updateFixTask = async (task: BugFixTaskRow, next: string) => {
    if (!detail) return;
    try {
      await api.patch(`/task-management/bug-fix-tasks/${task.id}`, { status: next });
      message.success(t('task.bug.taskUpdated'));
      await refreshDetail(detail.id);
    } catch {
      // API client 已统一提示错误
    }
  };

  const removeBug = (row: BugRow) => {
    Modal.confirm({
      title: t('common.confirmDelete'),
      content: t('common.confirmDelete'),
      okButtonProps: { danger: true },
      onOk: async () => {
        await api.delete(`/task-management/bugs/${row.id}`);
        message.success(t('common.deleted'));
        if (detail?.id === row.id) setDetail(null);
        await load();
      },
    });
  };

  const columns: ColumnsType<BugRow> = useMemo(() => [
    { title: t('task.bug.code'), dataIndex: 'bug_code', width: 140, fixed: 'left', render: (value, row) => <Button type="link" size="small" style={{ padding: 0 }} onClick={() => void refreshDetail(row.id)}>{value}</Button> },
    { title: t('task.title'), dataIndex: 'title', width: 260, ellipsis: true },
    { title: t('task.bug.system'), dataIndex: 'ci_name', width: 170, render: (v) => v || '-' },
    {
      title: t('task.priority'), dataIndex: 'priority', width: 90,
      render: (v: TicketPriority) => <Tag color={PRIORITY_COLORS[v]}>{v}</Tag>,
    },
    {
      title: t('common.status'), dataIndex: 'status', width: 140,
      render: (v: string) => <Tag color={BUG_STATUS[v]?.color}>{BUG_STATUS[v]?.label ?? v}</Tag>,
    },
    { title: t('task.bug.productManager'), dataIndex: 'product_manager_name', width: 110, render: (v) => v || '-' },
    { title: t('task.bug.devLeader'), dataIndex: 'dev_leader_name', width: 110, render: (v) => v || '-' },
    {
      title: t('common.actions'), key: 'actions', width: 180, fixed: 'right',
      render: (_: unknown, row: BugRow) => <Space size={0}>
        <Button type="link" size="small" onClick={() => void refreshDetail(row.id)}>{t('common.detail')}</Button>
        {row.capabilities.edit && <Button type="link" size="small" onClick={() => openEdit(row)}>{t('common.edit')}</Button>}
        {row.capabilities.delete && <Button type="link" size="small" danger onClick={() => removeBug(row)}>{t('common.delete')}</Button>}
      </Space>,
    },
  ], [t]);

  return (
    <div>
      <Space wrap style={{ marginBottom: 16 }}>
        <Select
          allowClear style={{ width: 160 }} placeholder={t('task.filter.status')}
          value={status} onChange={setStatus}
          options={Object.entries(BUG_STATUS).map(([value, item]) => ({ value, label: item.label }))}
        />
        <span>{t('task.filter.onlyMine')} <Switch checked={mineOnly} onChange={setMineOnly} /></span>
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>{t('common.refresh')}</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>{t('task.bug.register')}</Button>
      </Space>

      <Table<BugRow>
        rowKey="id" loading={loading} columns={columns} dataSource={rows}
        standardToolbar={{ exportFileName: 'Bug修复任务', searchPlaceholder: t('task.bug.search') }}
        sticky scroll={{ x: 1180 }} pagination={false}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('task.bug.empty')} /> }}
      />

      <Modal title={t('task.bug.register')} open={createOpen} onOk={() => void submitCreate()} confirmLoading={saving} onCancel={() => setCreateOpen(false)} destroyOnClose width={680}>
        <Form form={bugForm} layout="vertical" preserve={false}>
          <Form.Item name="title" label={t('task.title')} rules={[{ required: true, message: t('task.titleRequired') }]}><Input maxLength={200} /></Form.Item>
          <Form.Item name="ci_id" label={t('task.bug.system')} extra={t('task.bug.systemHint')} rules={[{ required: true, message: t('task.bug.systemRequired') }]}>
            <Select showSearch optionFilterProp="label" options={cis.map((ci) => ({ value: ci.id, label: `${ci.name}${ci.product_manager_name ? `（PM：${ci.product_manager_name}）` : ''}` }))} />
          </Form.Item>
          <Space wrap size={16}>
            <Form.Item name="priority" label={t('task.priority')} rules={[{ required: true }]}><Select style={{ width: 120 }} options={['P1', 'P2', 'P3', 'P4'].map((v) => ({ value: v, label: v }))} /></Form.Item>
            <Form.Item name="environment" label={t('task.bug.environment')}><Input style={{ width: 220 }} /></Form.Item>
          </Space>
          <Form.Item name="description" label={t('task.description')} rules={[{ required: true, message: t('task.descriptionRequired') }]}><Input.TextArea rows={3} maxLength={2000} /></Form.Item>
          <Form.Item name="reproduction" label={t('task.bug.reproduction')}><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="expected_result" label={t('task.bug.expected')}><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="actual_result" label={t('task.bug.actual')}><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="evidence" label={t('task.bug.evidence')}><Input.TextArea rows={2} /></Form.Item>
          <Form.Item label={t('task.bug.attachments')} extra={t('task.bug.attachmentHint')}>
            <Upload
              multiple
              beforeUpload={() => false}
              fileList={pendingFiles}
              onChange={({ fileList }) => setPendingFiles(fileList)}
            >
              <Button icon={<UploadOutlined />}>{t('task.bug.uploadAttachments')}</Button>
            </Upload>
          </Form.Item>
        </Form>
      </Modal>

      <Modal title={detail ? `${detail.bug_code} ${t('common.detail')}` : t('common.detail')} open={!!detail} onCancel={() => setDetail(null)} footer={null} width={960} destroyOnClose>
        {detail && <>
          <Space wrap style={{ marginBottom: 12 }}>
            <Tag color={BUG_STATUS[detail.status]?.color}>{BUG_STATUS[detail.status]?.label}</Tag>
            <Tag color={PRIORITY_COLORS[detail.priority]}>{detail.priority}</Tag>
            {detail.status === 'registered' && detail.capabilities.confirm && <Button type="primary" onClick={() => void (async () => { await api.post(`/task-management/bugs/${detail.id}/confirm`, { comment: '' }); message.success(t('task.bug.actionDone')); await refreshDetail(detail.id); })()}>{t('task.bug.confirm')}</Button>}
            {detail.status === 'registered' && detail.capabilities.confirm && <Button danger onClick={() => openAction('reject')}>{t('task.bug.reject')}</Button>}
            {detail.capabilities.edit && <Button onClick={() => openEdit(detail)}>{t('common.edit')}</Button>}
            {detail.capabilities.delete && <Button danger onClick={() => removeBug(detail)}>{t('common.delete')}</Button>}
            {detail.status === 'confirmed' && detail.capabilities.generate_fix_tasks && <Button type="primary" onClick={openGenerate}>{t('task.bug.generate')}</Button>}
            {detail.status === 'resolved' && detail.capabilities.verify && <><Button type="primary" onClick={() => openAction('verify-close')}>{t('task.bug.verifyClose')}</Button><Button onClick={() => openAction('verify-fail')}>{t('task.bug.verifyFail')}</Button></>}
            {['rejected', 'resolved', 'closed'].includes(detail.status) && detail.capabilities.reopen && <Button onClick={() => openAction('reopen')}>{t('task.bug.reopen')}</Button>}
          </Space>
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label={t('task.title')}>{detail.title}</Descriptions.Item>
            <Descriptions.Item label={t('task.bug.system')}>{detail.ci_name || '-'}</Descriptions.Item>
            <Descriptions.Item label={t('task.bug.productManager')}>{detail.product_manager_name || '-'}</Descriptions.Item>
            <Descriptions.Item label={t('task.bug.devLeader')}>{detail.dev_leader_name || '-'}</Descriptions.Item>
            <Descriptions.Item label={t('task.description')} span={2}>{detail.description}</Descriptions.Item>
            <Descriptions.Item label={t('task.bug.actual')} span={2}>{detail.actual_result || '-'}</Descriptions.Item>
            <Descriptions.Item label={t('task.bug.evidence')} span={2}>{detail.evidence || '-'}</Descriptions.Item>
            <Descriptions.Item label={t('task.bug.rejectionReason')} span={2}>{detail.rejection_reason || '-'}</Descriptions.Item>
          </Descriptions>
          <Divider orientation="left">{t('task.bug.attachments')}</Divider>
          <Space wrap>
            {attachments.length > 0 ? attachments.map((attachment) => (
              <Button
                key={attachment.id}
                size="small"
                icon={<DownloadOutlined />}
                onClick={() => void api.download(`/attachments/${attachment.id}/download`)}
              >
                {attachment.filename}
              </Button>
            )) : <Typography.Text type="secondary">{t('task.bug.noAttachments')}</Typography.Text>}
            {detail.capabilities.edit && (
              <Upload
                showUploadList={false}
                customRequest={({ file, onSuccess, onError }) => {
                  api.upload<AttachmentItem>(`/attachments?entity_type=bug&entity_id=${detail.id}`, file as File)
                    .then((result) => {
                      onSuccess?.(result);
                      message.success(t('task.bug.attachmentUploaded', { count: 1 }));
                      void loadAttachments(detail.id);
                    })
                    .catch((error) => onError?.(error as Error));
                }}
              >
                <Button size="small" type="dashed" icon={<UploadOutlined />}>{t('task.bug.uploadAttachments')}</Button>
              </Upload>
            )}
          </Space>
          <Divider orientation="left">{t('task.bug.fixTasks')}</Divider>
          <AntTable<BugFixTaskRow>
            rowKey="id" size="small" pagination={false} dataSource={detail.fix_tasks}
            columns={[
              { title: t('task.title'), dataIndex: 'name' },
              { title: t('task.bug.taskType'), dataIndex: 'task_type', width: 100 },
              { title: t('task.assignee'), dataIndex: 'assignee_name', width: 110, render: (v) => v || '-' },
              { title: t('common.status'), dataIndex: 'status', width: 90, render: (v) => <Tag>{v}</Tag> },
              { title: t('common.actions'), key: 'actions', width: 150, render: (_: unknown, row) => FIX_NEXT[row.status].length > 0 ? <Space size={0}>{FIX_NEXT[row.status].map((next) => <Button key={next} type="link" size="small" onClick={() => void updateFixTask(row, next)}>{next}</Button>)}</Space> : '-' },
            ]}
            locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('task.bug.noFixTasks')} /> }}
          />
          {detail.resolution_note && <Alert style={{ marginTop: 12 }} type="info" message={detail.resolution_note} />}
        </>}
      </Modal>

      <Modal
        title={editingBug ? `${t('common.edit')} · ${editingBug.bug_code}` : t('common.edit')}
        open={!!editingBug}
        onOk={() => void submitEdit()}
        confirmLoading={saving}
        onCancel={() => setEditingBug(null)}
        destroyOnClose
        width={680}
      >
        <Form form={bugForm} layout="vertical" preserve={false}>
          <Form.Item name="title" label={t('task.title')} rules={[{ required: true, message: t('task.titleRequired') }]}><Input maxLength={200} /></Form.Item>
          <Form.Item name="ci_id" label={t('task.bug.system')} extra={t('task.bug.systemHint')} rules={[{ required: true, message: t('task.bug.systemRequired') }]}>
            <Select showSearch optionFilterProp="label" options={cis.map((ci) => ({ value: ci.id, label: `${ci.name}${ci.product_manager_name ? `（PM：${ci.product_manager_name}）` : ''}` }))} />
          </Form.Item>
          <Space wrap size={16}>
            <Form.Item name="priority" label={t('task.priority')} rules={[{ required: true }]}><Select style={{ width: 120 }} options={['P1', 'P2', 'P3', 'P4'].map((v) => ({ value: v, label: v }))} /></Form.Item>
            <Form.Item name="environment" label={t('task.bug.environment')}><Input style={{ width: 220 }} /></Form.Item>
          </Space>
          <Form.Item name="description" label={t('task.description')} rules={[{ required: true, message: t('task.descriptionRequired') }]}><Input.TextArea rows={3} maxLength={2000} /></Form.Item>
          <Form.Item name="reproduction" label={t('task.bug.reproduction')}><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="expected_result" label={t('task.bug.expected')}><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="actual_result" label={t('task.bug.actual')}><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="evidence" label={t('task.bug.evidence')}><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>

      <Modal title={action === 'reject' ? t('task.bug.reject') : action === 'reopen' ? t('task.bug.reopen') : action === 'verify-close' ? t('task.bug.verifyClose') : t('task.bug.verifyFail')} open={!!action} onOk={() => void submitAction()} confirmLoading={actionSaving} onCancel={() => setAction(null)} destroyOnClose>
        <Form form={actionForm} layout="vertical"><Form.Item name="reason" label={action === 'verify-close' ? t('task.bug.verificationNote') : t('common.remark')} rules={[{ required: true, min: 2, message: t('task.reasonRequired') }]}><Input.TextArea rows={4} maxLength={1000} /></Form.Item></Form>
      </Modal>

      <Modal title={t('task.bug.generate')} open={fixOpen} onOk={() => void submitGenerate()} confirmLoading={saving} onCancel={() => setFixOpen(false)} destroyOnClose width={760}>
        <Form form={fixForm} layout="vertical">
          <Form.List name="tasks">
            {(fields, { add, remove }) => <>
              {fields.map((field) => <Card size="small" key={field.key} style={{ marginBottom: 10 }} extra={<Button type="link" danger onClick={() => remove(field.name)}>{t('common.delete')}</Button>}>
                <Space wrap align="start">
                  <Form.Item {...field} name={[field.name, 'name']} label={t('task.title')} rules={[{ required: true, message: t('task.titleRequired') }]}><Input style={{ width: 220 }} /></Form.Item>
                  <Form.Item {...field} name={[field.name, 'task_type']} label={t('task.bug.taskType')}><Select style={{ width: 110 }} options={['开发', '测试', '发布'].map((v) => ({ value: v, label: v }))} /></Form.Item>
                  <Form.Item {...field} name={[field.name, 'assignee']} label={t('task.assignee')} rules={[{ required: true, message: t('task.assigneeRequired') }]}><Select showSearch optionFilterProp="label" style={{ width: 150 }} options={members.map((m) => ({ value: m.id, label: m.name }))} /></Form.Item>
                  <Form.Item {...field} name={[field.name, 'plan_date']} label={t('task.planDate')}><DatePicker /></Form.Item>
                  <Form.Item {...field} name={[field.name, 'plan_effort']} label={t('task.planEffort')}><InputNumber min={0} precision={1} /></Form.Item>
                </Space>
                <Form.Item {...field} name={[field.name, 'description']} label={t('task.description')}><Input.TextArea rows={2} /></Form.Item>
              </Card>)}
              <Button type="dashed" block icon={<PlusOutlined />} onClick={() => add({ task_type: '开发' })}>{t('task.bug.addFixTask')}</Button>
            </>}
          </Form.List>
        </Form>
      </Modal>
    </div>
  );
}
