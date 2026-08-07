import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  Badge,
  Button,
  Card,
  Collapse,
  DatePicker,
  Drawer,
  Form,
  Image,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Tag,
  Upload,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import Table from '../../components/SortableTable';
import { PaperClipOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { api } from '../../api/client';
import { ExampleTag } from '../../components/ExampleTag';
import PendingStepCell from '../../components/PendingStepCell';
import type { PendingStep } from '../../components/PendingStepCell';
import { useT } from '../../i18n';
import { useAuthStore, hasPermission } from '../../stores/auth';
import { useEnums } from '../../i18n/enums';
import type { AttachmentItem, Member, ServiceFormField, ServiceItem, ServiceItemFormVersion, TicketPriority, TicketRow, TicketType } from '../../api/types';
import { PRIORITY_COLORS } from '../../api/types';
import DocumentTypeHint from '../../components/DocumentTypeHint';

/** 状态 → Badge 样式（按语义猜测，未匹配用 processing；含变更状态机 rejected/rolled_back） */
function statusBadge(status: string): 'default' | 'success' | 'error' | 'warning' | 'processing' {
  if (status === 'closed' || status === 'cancelled') return 'default';
  if (status === 'resolved' || status === 'approved') return 'success';
  if (status === 'rejected' || status === 'rolled_back') return 'error';
  if (status === 'paused' || status === 'pending_approval') return 'warning';
  return 'processing';
}

/** SLA 达成状态渲染 */
export function renderSla(
  row: {
    sla_resolution_met: boolean | null;
    sla_warned: boolean;
  },
  t: (key: string) => string,
): JSX.Element | string {
  if (row.sla_resolution_met === true) return <Tag color="green">{t('itsm.sla.metMark')}</Tag>;
  if (row.sla_resolution_met === false) return <Tag color="red">{t('itsm.sla.overdueMark')}</Tag>;
  if (row.sla_warned) return <Tag color="orange">{t('itsm.sla.dueMark')}</Tag>;
  return '-';
}

interface TicketFormValues {
  title: string;
  priority: TicketPriority;
  description: string;
  service_item_id: string;
  service_category?: string;
  other_info?: string;
  assignee?: string;
  remarks?: string;
  change_type?: string;
  risk_level?: string;
  change_reason?: string;
  rollback_plan?: string;
  planned_window?: [Dayjs, Dayjs];
  implementation_plan?: string;
  request_data?: Record<string, unknown>;
}

type TicketDraftAttachment = AttachmentItem & { previewUrl?: string };

const MAX_SERVICE_REQUEST_ATTACHMENTS = 10;

/** 工单类型 → 权限模块（M17.2 按类型独立授权） */
const TYPE_MODULE: Record<TicketType, string> = {
  service_request: 'ticket_sr',
  incident: 'ticket_incident',
  change: 'ticket_change',
};

export default function Tickets({ fixedType }: { fixedType: TicketType }) {
  const authUser = useAuthStore((st) => st.user);
  const canCreate = authUser?.permissions ? hasPermission(authUser, TYPE_MODULE[fixedType], 'create') : true;
  // M20 列表管理动作：编辑/关闭按类型模块 edit；删除按 delete（默认矩阵仅 admin）
  const canEdit = hasPermission(authUser, TYPE_MODULE[fixedType], 'edit');
  const canDelete = hasPermission(authUser, TYPE_MODULE[fixedType], 'delete');
  // M28（用户定稿）：admin 恒可强关；服务请求登记人本人可关（理由+审计）；事件/变更走流程闭环
  const isAdmin = !!authUser?.permissions?.['*'];
  const canCloseRow = (r: TicketRow): boolean =>
    isAdmin || (fixedType === 'service_request' && !!r.submitter && r.submitter === authUser?.id);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const createRequested = searchParams.get('create') === '1';
  const t = useT();
  const et = useEnums();
  const [items, setItems] = useState<TicketRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);

  // 筛选（类型固定为 fixedType，不再提供类型筛选）
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<string | undefined>();
  const [priority, setPriority] = useState<TicketPriority | undefined>();
  const [mineOnly, setMineOnly] = useState(false);
  // 状态筛选选项：从已加载数据中累积（code → 中文名）
  const [statusOptions, setStatusOptions] = useState<Record<string, string>>({});

  // 新建 Drawer
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<TicketFormValues>();
  const [serviceItems, setServiceItems] = useState<ServiceItem[]>([]);
  const [serviceItemsLoading, setServiceItemsLoading] = useState(false);
  const [serviceForm, setServiceForm] = useState<ServiceItemFormVersion | null>(null);
  const [serviceFormLoading, setServiceFormLoading] = useState(false);
  const [draftAttachments, setDraftAttachments] = useState<TicketDraftAttachment[]>([]);
  const [attachmentUploading, setAttachmentUploading] = useState(0);
  const [members, setMembers] = useState<Member[]>([]);
  const directCreateStarted = useRef(false);

  const isServiceRequest = fixedType === 'service_request';
  const showInternalFields = !isServiceRequest || canEdit || isAdmin;
  const serviceCategoryOptions = useMemo(() => {
    const names = new Set<string>();
    serviceItems.forEach((item) => {
      if (item.catalog_name) names.add(item.catalog_name);
    });
    return [...names].map((name) => ({ value: name, label: name }));
  }, [serviceItems]);

  const serviceItemsForCategory = (category?: string) =>
    serviceItems.filter((item) => item.catalog_name === category || item.name === category);

  const loadServiceForm = async (itemId?: string) => {
    setServiceForm(null);
    if (!itemId || !isServiceRequest) return;
    setServiceFormLoading(true);
    try {
      const current = await api.get<ServiceItemFormVersion>(`/service-items/${itemId}/form`);
      setServiceForm(current);
      const defaults: Record<string, unknown> = {};
      Object.entries(current.schema.properties).forEach(([code, definition]) => {
        if (definition.default !== undefined) defaults[code] = definition.default;
      });
      form.setFieldValue('request_data', defaults);
      if (typeof defaults.priority === 'string') {
        form.setFieldValue('priority', defaults.priority as TicketPriority);
      }
    } catch {
      setServiceForm(null);
    } finally {
      setServiceFormLoading(false);
    }
  };

  const renderDynamicField = (code: string, definition: ServiceFormField, required: boolean) => {
    const rules = required ? [{ required: true, message: `请填写${definition.title}` }] : undefined;
    const common = { name: ['request_data', code], label: definition.title, rules };
    if (definition.type === 'boolean') {
      return <Form.Item key={code} {...common} valuePropName="checked"><Switch /></Form.Item>;
    }
    if (definition.type === 'integer' || definition.type === 'number') {
      return (
        <Form.Item key={code} {...common}>
          <InputNumber
            precision={definition.type === 'integer' ? 0 : undefined}
            min={definition.minimum}
            max={definition.maximum}
            style={{ width: '100%' }}
          />
        </Form.Item>
      );
    }
    if (definition.type === 'array') {
      const options = definition.items?.enum ?? definition.enum;
      return (
        <Form.Item key={code} {...common}>
          <Select
            mode={options ? 'multiple' : 'tags'}
            options={options?.map((value) => ({ value, label: String(value) }))}
          />
        </Form.Item>
      );
    }
    if (definition.enum) {
      return (
        <Form.Item key={code} {...common}>
          <Select options={definition.enum.map((value) => ({ value, label: String(value) }))} />
        </Form.Item>
      );
    }
    if (definition.format === 'date') {
      return <Form.Item key={code} {...common}><DatePicker style={{ width: '100%' }} /></Form.Item>;
    }
    if (definition['x-itom-field-type'] === 'long_text') {
      return (
        <Form.Item key={code} {...common}>
          <Input.TextArea rows={3} maxLength={definition.maxLength} />
        </Form.Item>
      );
    }
    return <Form.Item key={code} {...common}><Input maxLength={definition.maxLength} /></Form.Item>;
  };

  // M20 行内编辑 / 关闭
  const [editing, setEditing] = useState<TicketRow | null>(null);
  const [editSaving, setEditSaving] = useState(false);
  const [editForm] = Form.useForm<{ title: string; priority: TicketPriority; assignee?: string; description?: string; remarks?: string }>();
  const [closing, setClosing] = useState<TicketRow | null>(null);
  const [closeReason, setCloseReason] = useState('');
  const [closeSaving, setCloseSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<TicketRow>('/tickets', {
        page,
        page_size: pageSize,
        q: q || undefined,
        status: status || undefined,
        ticket_type: fixedType,
        priority: priority || undefined,
        scope: mineOnly ? 'mine' : undefined,
      });
      setItems(res.items);
      setTotal(res.total);
      setStatusOptions((prev) => {
        const next = { ...prev };
        res.items.forEach((t) => {
          if (t.status && !next[t.status]) next[t.status] = t.status_name || t.status;
        });
        return next;
      });
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, q, status, fixedType, priority, mineOnly]);

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = () => {
    // 正常关闭会清理临时附件；这里再释放一次浏览器预览 URL，避免异常关闭
    // 或重复触发“创建”入口时泄漏本地对象引用。
    draftAttachments.forEach((attachment) => {
      if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
    });
    form.resetFields();
    setServiceForm(null);
    setDraftAttachments([]);
    setAttachmentUploading(0);
    setDrawerOpen(true);
    if (serviceItems.length === 0) {
      setServiceItemsLoading(true);
      api
        .getList<ServiceItem>('/service-items')
        .then((res) => {
          const liveItems = res.items.filter((i) => i.status === '上架');
          setServiceItems(liveItems);
        })
        .catch(() => undefined)
        .finally(() => setServiceItemsLoading(false));
    }
    if (members.length === 0) {
      api
        .getList<Member>('/members', { page: 1, page_size: 2000, scope: 'it' })
        .then((res) => setMembers(res.items))
        .catch(() => undefined);
    }
  };

  const discardDraftAttachments = async (attachments = draftAttachments) => {
    attachments.forEach((attachment) => {
      if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
    });
    setDraftAttachments([]);
    await Promise.allSettled(attachments.map((attachment) => api.delete(`/attachments/ticket-drafts/${attachment.id}`)));
  };

  const closeCreate = () => {
    void discardDraftAttachments();
    setDrawerOpen(false);
  };

  const stageTicketAttachment = async (file: File) => {
    if (draftAttachments.length + attachmentUploading >= MAX_SERVICE_REQUEST_ATTACHMENTS) {
      message.warning(t('itsm.ticket.attachmentLimit'));
      return;
    }
    const previewUrl = file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined;
    setAttachmentUploading((count) => count + 1);
    try {
      const uploaded = await api.upload<AttachmentItem>('/attachments/ticket-drafts', file);
      setDraftAttachments((items) => [...items, { ...uploaded, previewUrl }]);
    } catch {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      // 已统一提示
    } finally {
      setAttachmentUploading((count) => Math.max(0, count - 1));
    }
  };

  const removeDraftAttachment = async (attachment: TicketDraftAttachment) => {
    try {
      await api.delete(`/attachments/ticket-drafts/${attachment.id}`);
      if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
      setDraftAttachments((items) => items.filter((item) => item.id !== attachment.id));
    } catch {
      // 已统一提示
    }
  };

  // create=1 直达新建表单；一次性 guard 避免 React StrictMode 重复打开。
  useEffect(() => {
    if (!createRequested || !canCreate || directCreateStarted.current) return;
    directCreateStarted.current = true;
    openCreate();
    // openCreate intentionally captures the current form/service-item loaders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fixedType, createRequested, canCreate]);

  const handleCreate = async () => {
    if (attachmentUploading > 0) {
      message.warning(t('itsm.ticket.attachmentUploading'));
      return;
    }
    const values = await form.validateFields();
    const payload: Record<string, unknown> = {
      title: values.title,
      ticket_type: fixedType,
      priority: values.priority,
      description: values.description,
      service_item_id: values.service_item_id,
    };
    if (isServiceRequest) {
      if (values.service_category) payload.service_category = values.service_category;
      if (values.other_info) payload.other_info = values.other_info;
      const requestData = { ...(values.request_data ?? {}) };
      Object.entries(requestData).forEach(([code, value]) => {
        if (dayjs.isDayjs(value)) requestData[code] = value.format('YYYY-MM-DD');
      });
      requestData.title = values.title;
      requestData.description = values.description;
      if (serviceForm?.schema.properties.priority) requestData.priority = values.priority;
      payload.request_data = requestData;
      payload.request_form_version_id = serviceForm?.id;
      payload.attachment_ids = draftAttachments.map((attachment) => attachment.id);
    }
    if (values.assignee != null) payload.assignee = values.assignee;
    if (values.remarks) payload.remarks = values.remarks;
    if (fixedType === 'change') {
      payload.change_type = values.change_type;
      payload.risk_level = values.risk_level;
      if (values.change_reason) payload.change_reason = values.change_reason;
      if (values.rollback_plan) payload.rollback_plan = values.rollback_plan;
      if (values.implementation_plan) payload.implementation_plan = values.implementation_plan;
      if (values.planned_window) {
        payload.planned_start_at = values.planned_window[0].format('YYYY-MM-DD HH:mm:ss');
        payload.planned_end_at = values.planned_window[1].format('YYYY-MM-DD HH:mm:ss');
      }
    }
    setSaving(true);
    try {
      const created = await api.post<{ id: string }>('/tickets', payload);
      message.success(t('itsm.ticket.createdTyped', { type: et.ticketType(fixedType) }));
      setDrawerOpen(false);
      if (created?.id) {
        draftAttachments.forEach((attachment) => {
          if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
        });
        setDraftAttachments([]);
        navigate(`/itsm/tickets/${created.id}`);
      } else {
        void load();
      }
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  // ---- M20 行内管理动作 ----
  const loadMembers = () => {
    if (members.length === 0) {
      api
        .getList<Member>('/members', { page: 1, page_size: 2000, scope: 'it' })
        .then((res) => setMembers(res.items))
        .catch(() => undefined);
    }
  };

  const openEdit = async (row: TicketRow) => {
    loadMembers();
    setEditing(row);
    try {
      const d = await api.get<{ title: string; priority: TicketPriority; assignee: string | null; description: string | null; remarks: string | null }>(`/tickets/${row.id}`);
      editForm.setFieldsValue({
        title: d.title,
        priority: d.priority,
        assignee: d.assignee ?? undefined,
        description: d.description ?? '',
        remarks: d.remarks ?? '',
      });
    } catch {
      setEditing(null);
    }
  };

  const handleEditSave = async () => {
    if (!editing) return;
    const v = await editForm.validateFields();
    const isUpstreamCorrection = editing.workflow_edit_mode?.startsWith('upstream_') === true;
    setEditSaving(true);
    try {
      await api.patch(`/tickets/${editing.id}`, {
        title: v.title,
        priority: v.priority,
        description: v.description,
        remarks: v.remarks,
        // 回改窗口仅允许更正业务内容，不能借此改派下一节点。
        ...(isUpstreamCorrection ? {} : { assignee: v.assignee ?? null }),
      });
      message.success(t('itsm.ticket.updatedMsg'));
      setEditing(null);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setEditSaving(false);
    }
  };

  const handleClose = async () => {
    if (!closing) return;
    if (closeReason.trim().length < 5) {
      message.warning(t('itsm.ticket.closeReasonRequired'));
      return;
    }
    setCloseSaving(true);
    try {
      await api.post(`/tickets/${closing.id}/close`, { reason: closeReason.trim() });
      message.success(t('itsm.ticket.closedMsg'));
      setClosing(null);
      setCloseReason('');
      void load();
    } catch {
      // 已统一提示
    } finally {
      setCloseSaving(false);
    }
  };

  const handleDelete = async (row: TicketRow) => {
    try {
      await api.delete(`/tickets/${row.id}`);
      message.success(t('itsm.ticket.deletedMsg'));
      void load();
    } catch {
      // 已统一提示
    }
  };

  const columns: ColumnsType<TicketRow> = [
    {
      title: t('itsm.f.code'),
      dataIndex: 'ticket_code',
      width: 140,
      fixed: 'left',
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (v: string, r) => (
        <Space size={4}>
          <Link to={`/itsm/tickets/${r.id}`}>{v}</Link>
          {r.is_example && <ExampleTag />}
        </Space>
      ),
    },
    { title: t('itsm.f.title'), dataIndex: 'title', width: 220, ellipsis: true },
    {
      title: t('itsm.f.priority'),
      dataIndex: 'priority',
      width: 80,
      render: (v: TicketPriority) => <Tag color={PRIORITY_COLORS[v]}>{v}</Tag>,
    },
    {
      title: t('common.status'),
      dataIndex: 'status_name',
      width: 110,
      render: (v: string, r) => <Badge status={statusBadge(r.status)} text={v || r.status} />,
    },
    { title: t('itsm.f.serviceItem'), dataIndex: 'service_item_name', width: 150, ellipsis: true, render: (v) => v || '-' },
    { title: t('itsm.f.assignee'), dataIndex: 'assignee_name', width: 100, render: (v) => v || '-' },
    {
      title: t('itsm.f.submitter'),
      dataIndex: 'submitter_name',
      width: 120,
      render: (v: string | null, r) => (v ? `${v}${r.submitter_dept ? `(${r.submitter_dept})` : ''}` : '-'),
    },
    {
      title: t('itsm.f.submittedAt'),
      dataIndex: 'submitted_at',
      width: 150,
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'),
    },
    { title: 'SLA', key: 'sla', width: 90, render: (_, r) => renderSla(r, t) },
    {
      title: t('comp.pending.col'),
      key: 'pending',
      width: 190,
      render: (_, r) => <PendingStepCell pending={(r as TicketRow & { pending_step?: PendingStep | null }).pending_step} onGo={() => navigate(`/itsm/tickets/${r.id}`)} />,
    },
    // M20：管理动作列（编辑/关闭需 edit；删除需 delete——默认矩阵仅 admin），示例数据只读
    ...(canEdit || canDelete || fixedType === 'service_request' || isAdmin || items.some((item) => item.can_edit || item.can_delete)
      ? ([
          {
            title: t('common.actions'),
            key: 'actions',
            width: 150,
            fixed: 'right' as const,
            render: (_: unknown, r: TicketRow) =>
              r.is_example && !isAdmin ? null : (
                <Space size={8}>
                  {(r.can_edit ?? canEdit) && r.status !== 'closed' && r.status !== 'rejected' && (
                    <Button type="link" size="small" style={{ padding: 0 }} onClick={() => void openEdit(r)}>
                      {t('common.edit')}
                    </Button>
                  )}
                  {canCloseRow(r) && r.status !== 'closed' && r.status !== 'rejected' && (
                    <Button
                      type="link"
                      size="small"
                      style={{ padding: 0 }}
                      onClick={() => {
                        setCloseReason('');
                        setClosing(r);
                      }}
                    >
                      {t('itsm.ticket.close')}
                    </Button>
                  )}
                  {(r.can_delete ?? canDelete) && (
                    <Popconfirm title={t('itsm.ticket.deleteConfirm')} onConfirm={() => void handleDelete(r)}>
                      <Button type="link" size="small" danger style={{ padding: 0 }}>
                        {t('common.delete')}
                      </Button>
                    </Popconfirm>
                  )}
                </Space>
              ),
          },
        ] as ColumnsType<TicketRow>)
      : []),
  ];

  return (
    <Card
      title={t('itsm.ticket.title.' + fixedType)}
      extra={
        canCreate && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openCreate()}>
            {t('itsm.ticket.createTyped', { type: et.ticketType(fixedType) })}
          </Button>
        )
      }
    >
      <DocumentTypeHint documentType={fixedType} />
      <Space wrap style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder={t('itsm.searchCodeTitle')}
          allowClear
          style={{ width: 220 }}
          onSearch={(v) => {
            setPage(1);
            setQ(v);
          }}
        />
        <Select
          placeholder={t('common.status')}
          allowClear
          style={{ width: 130 }}
          value={status}
          onChange={(v) => {
            setPage(1);
            setStatus(v);
          }}
          options={Object.entries(statusOptions).map(([value, label]) => ({ value, label }))}
        />
        <Select
          placeholder={t('itsm.f.priority')}
          allowClear
          style={{ width: 110 }}
          value={priority}
          onChange={(v) => {
            setPage(1);
            setPriority(v);
          }}
          options={(['P1', 'P2', 'P3', 'P4'] as TicketPriority[]).map((p) => ({ value: p, label: p }))}
        />
        <span>
          {t('itsm.ticket.mineOnly')}{' '}
          <Switch
            checked={mineOnly}
            onChange={(v) => {
              setPage(1);
              setMineOnly(v);
            }}
          />
        </span>
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>
          {t('common.refresh')}
        </Button>
      </Space>

      <Table<TicketRow>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        standardToolbar={{ exportFileName: '工单清单', showSearch: false, showFilter: false }}
        sticky
        scroll={{ x: 1300 }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (n) => t('itsm.total', { n }),
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
      />

      <Drawer
        title={t('itsm.ticket.createTyped', { type: et.ticketType(fixedType) })}
        open={drawerOpen}
        width={560}
        onClose={closeCreate}
        destroyOnClose
        extra={
          <Space>
            <Button onClick={closeCreate}>{t('common.cancel')}</Button>
            <Button type="primary" loading={saving} onClick={() => void handleCreate()}>
              {t('common.submit')}
            </Button>
          </Space>
        }
      >
        <DocumentTypeHint documentType={fixedType} />
        <Form<TicketFormValues>
          form={form}
          layout="vertical"
          preserve={false}
          initialValues={{ priority: 'P3' }}
        >
          {isServiceRequest ? (
            <>
              <Form.Item label={t('itsm.ticket.user')}>
                <Input disabled value={authUser?.name || authUser?.username || '-'} />
              </Form.Item>
              <Form.Item name="title" label={t('itsm.f.title')} rules={[{ required: true, message: t('itsm.rule.title') }]}>
                <Input maxLength={200} placeholder={t('itsm.ticket.titlePlaceholder')} />
              </Form.Item>
              <Form.Item name="priority" label={t('itsm.ticket.urgency')} rules={[{ required: true, message: t('itsm.rule.priority') }]}>
                <Select
                  options={([
                    ['P1', 'itsm.ticket.priorityUrgent'],
                    ['P2', 'itsm.ticket.priorityHigh'],
                    ['P3', 'itsm.ticket.priorityNormal'],
                    ['P4', 'itsm.ticket.priorityLow'],
                  ] as [TicketPriority, string][]).map(([value, label]) => ({ value, label: t(label) }))}
                />
              </Form.Item>
              <Form.Item
                name="service_category"
                label={t('itsm.ticket.serviceCategory')}
                rules={[{ required: true, message: t('itsm.ticket.serviceCategoryRequired') }]}
              >
                <Select
                  showSearch
                  optionFilterProp="label"
                  loading={serviceItemsLoading}
                  placeholder={t('itsm.ticket.serviceCategoryPlaceholder')}
                  options={serviceCategoryOptions}
                  onChange={(value: string) => {
                    const matches = serviceItemsForCategory(value);
                    const itemId = matches.length === 1 ? matches[0].id : undefined;
                    form.setFieldValue('service_item_id', itemId);
                    void loadServiceForm(itemId);
                  }}
                />
              </Form.Item>
              <Form.Item noStyle shouldUpdate={(prev, next) => prev.service_category !== next.service_category}>
                {({ getFieldValue }) => {
                  const category = getFieldValue('service_category') as string | undefined;
                  const matches = serviceItemsForCategory(category);
                  if (matches.length === 1) {
                    return <Form.Item name="service_item_id" hidden><Input /></Form.Item>;
                  }
                  return (
                    <Form.Item
                      name="service_item_id"
                      label={t('itsm.ticket.serviceItemDetail')}
                      rules={[{ required: true, message: t('itsm.rule.serviceItem') }]}
                    >
                      <Select
                        showSearch
                        optionFilterProp="label"
                        disabled={!category || serviceItemsLoading}
                        placeholder={category ? t('itsm.ticket.serviceItemDetailPlaceholder') : t('itsm.ticket.chooseCategoryFirst')}
                        options={matches.map((i) => ({ value: i.id, label: i.name }))}
                        onChange={(itemId: string) => void loadServiceForm(itemId)}
                      />
                    </Form.Item>
                  );
                }}
              </Form.Item>
              <Form.Item
                name="description"
                label={t('itsm.ticket.problemDescription')}
                rules={[{ required: true, message: t('itsm.rule.description') }]}
              >
                <Input.TextArea rows={5} maxLength={2000} placeholder={t('itsm.ticket.descPlaceholder')} />
              </Form.Item>
              <Form.Item name="other_info" label={t('itsm.ticket.otherInfo')}>
                <Input.TextArea
                  rows={3}
                  maxLength={1000}
                  placeholder={t('itsm.ticket.otherInfoPlaceholder')}
                  onPaste={(event) => {
                    const files = Array.from(event.clipboardData.files);
                    if (files.length === 0) return;
                    event.preventDefault();
                    files.forEach((file) => void stageTicketAttachment(file));
                  }}
                />
              </Form.Item>
              <Form.Item
                label={t('itsm.ticket.attachments')}
                extra={t('itsm.ticket.attachmentHint')}
              >
                <Space direction="vertical" style={{ width: '100%' }} size={8}>
                  <Upload
                    multiple
                    showUploadList={false}
                    beforeUpload={(file) => {
                      void stageTicketAttachment(file);
                      return Upload.LIST_IGNORE;
                    }}
                    accept=".png,.jpg,.jpeg,.gif,.webp,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv"
                  >
                    <Button icon={<PaperClipOutlined />} loading={attachmentUploading > 0}>
                      {t('itsm.ticket.uploadAttachment')}
                    </Button>
                  </Upload>
                  {draftAttachments.length > 0 && (
                    <Space wrap size={[8, 8]}>
                      {draftAttachments.map((attachment) => (
                        <Tag
                          key={attachment.id}
                          closable
                          onClose={(event) => {
                            event.preventDefault();
                            void removeDraftAttachment(attachment);
                          }}
                          icon={<PaperClipOutlined />}
                        >
                          {attachment.previewUrl && (
                            <Image
                              preview={{ src: attachment.previewUrl }}
                              src={attachment.previewUrl}
                              width={28}
                              height={28}
                              style={{ objectFit: 'cover', marginRight: 6, verticalAlign: 'middle' }}
                            />
                          )}
                          {attachment.filename}
                        </Tag>
                      ))}
                    </Space>
                  )}
                </Space>
              </Form.Item>
              {serviceFormLoading && <Card size="small" loading style={{ marginBottom: 16 }} />}
              {serviceForm && Object.entries(serviceForm.schema.properties)
                .filter(([code]) => !['title', 'description', 'priority'].includes(code))
                .map(([code, definition]) => renderDynamicField(
                  code,
                  definition,
                  (serviceForm.schema.required ?? []).includes(code),
                ))}
              <Form.Item label={t('itsm.ticket.agent')}>
                <Input disabled value={t('itsm.ticket.agentPending')} />
              </Form.Item>
            </>
          ) : (
            <>
              <Form.Item name="title" label={t('itsm.f.title')} rules={[{ required: true, message: t('itsm.rule.title') }]}>
                <Input maxLength={200} placeholder={t('itsm.ticket.titlePlaceholder')} />
              </Form.Item>
              <Form.Item name="priority" label={t('itsm.f.priority')} rules={[{ required: true, message: t('itsm.rule.priority') }]}>
                <Select options={(['P1', 'P2', 'P3', 'P4'] as TicketPriority[]).map((p) => ({ value: p, label: p }))} />
              </Form.Item>
              <Form.Item name="description" label={t('itsm.f.description')} rules={[{ required: true, message: t('itsm.rule.description') }]}>
                <Input.TextArea rows={4} maxLength={2000} placeholder={t('itsm.ticket.descPlaceholder')} />
              </Form.Item>
              <Form.Item name="service_item_id" label={t('itsm.f.serviceItem')} rules={[{ required: true, message: t('itsm.rule.serviceItem') }]}>
                <Select
                  showSearch
                  optionFilterProp="label"
                  loading={serviceItemsLoading}
                  placeholder={t('itsm.selectServiceItem')}
                  options={serviceItems.map((i) => ({ value: i.id, label: `${i.name}（${i.catalog_name ?? i.item_code}）` }))}
                />
              </Form.Item>
            </>
          )}

          {fixedType === 'change' && (
            <Card size="small" title={t('itsm.ticket.changeInfo')} style={{ marginBottom: 16 }}>
              <Form.Item
                name="change_type"
                label={t('itsm.ticket.changeType')}
                rules={[{ required: true, message: t('itsm.ticket.changeTypeRequired') }]}
              >
                <Select
                  options={['标准', '普通', '紧急'].map((v) => ({ value: v, label: et.changeType(v) }))}
                  placeholder={t('itsm.ticket.changeTypePlaceholder')}
                />
              </Form.Item>
              <Form.Item
                name="risk_level"
                label={t('itsm.ticket.riskLevel')}
                rules={[{ required: true, message: t('itsm.ticket.riskLevelRequired') }]}
              >
                <Select options={['高', '中', '低'].map((v) => ({ value: v, label: et.riskGrade(v) }))} />
              </Form.Item>
              <Form.Item name="change_reason" label={t('itsm.ticket.changeReason')}>
                <Input.TextArea rows={2} maxLength={1000} />
              </Form.Item>
              <Form.Item name="rollback_plan" label={t('itsm.ticket.rollbackPlan')}>
                <Input.TextArea rows={2} maxLength={1000} />
              </Form.Item>
              <Form.Item name="planned_window" label={t('itsm.ticket.changeWindow')}>
                <DatePicker.RangePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="implementation_plan" label={t('itsm.ticket.implementationPlan')}>
                <Input.TextArea rows={2} maxLength={2000} />
              </Form.Item>
            </Card>
          )}

          {showInternalFields && (
            <Collapse
              ghost
              items={[
                {
                  key: 'more',
                  label: isServiceRequest ? t('itsm.ticket.internalOptions') : t('itsm.ticket.moreOptions'),
                  children: (
                    <>
                      <Form.Item name="assignee" label={t('itsm.f.assignee')}>
                        <Select
                          allowClear
                          showSearch
                          optionFilterProp="label"
                          placeholder={t('itsm.ticket.assigneePlaceholder')}
                          options={members.map((m) => ({
                            value: m.id,
                            label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
                          }))}
                        />
                      </Form.Item>
                      <Form.Item name="remarks" label={t('common.remark')}>
                        <Input.TextArea rows={2} maxLength={500} />
                      </Form.Item>
                    </>
                  ),
                },
              ]}
            />
          )}
        </Form>
      </Drawer>

      {/* M20 行内编辑（核心字段；改派/流转在详情页） */}
      <Modal
        title={editing ? `${t('itsm.ticket.editTitle')} · ${editing.ticket_code}` : t('itsm.ticket.editTitle')}
        open={!!editing}
        confirmLoading={editSaving}
        onOk={() => void handleEditSave()}
        onCancel={() => setEditing(null)}
        destroyOnClose
      >
        <Form form={editForm} layout="vertical" preserve={false}>
          <Form.Item name="title" label={t('itsm.f.title')} rules={[{ required: true, message: t('itsm.rule.title') }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="priority" label={t('itsm.f.priority')} rules={[{ required: true, message: t('itsm.rule.priority') }]}>
            <Select options={(['P1', 'P2', 'P3', 'P4'] as TicketPriority[]).map((p) => ({ value: p, label: p }))} />
          </Form.Item>
          {!editing?.workflow_edit_mode?.startsWith('upstream_') && (
            <Form.Item name="assignee" label={t('itsm.f.assignee')}>
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                options={members.map((m) => ({
                  value: m.id,
                  label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
                }))}
              />
            </Form.Item>
          )}
          <Form.Item name="description" label={t('itsm.f.description')}>
            <Input.TextArea rows={4} maxLength={2000} />
          </Form.Item>
          <Form.Item name="remarks" label={t('common.remark')}>
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>

      {/* M20 关闭工单：理由必填（≥5 字），沿状态机路径推进至已关闭 */}
      <Modal
        title={closing ? `${t('itsm.ticket.closeTitle')} · ${closing.ticket_code}` : t('itsm.ticket.closeTitle')}
        open={!!closing}
        confirmLoading={closeSaving}
        okButtonProps={{ danger: true }}
        onOk={() => void handleClose()}
        onCancel={() => {
          setClosing(null);
          setCloseReason('');
        }}
        destroyOnClose
      >
        <div style={{ marginBottom: 8 }}>{t('itsm.ticket.closeReason')}</div>
        <Input.TextArea
          rows={3}
          maxLength={500}
          value={closeReason}
          onChange={(e) => setCloseReason(e.target.value)}
          placeholder={t('itsm.ticket.closeReasonPlaceholder')}
        />
      </Modal>
    </Card>
  );
}
