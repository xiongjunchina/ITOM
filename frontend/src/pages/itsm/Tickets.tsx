import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Badge,
  Button,
  Card,
  Collapse,
  DatePicker,
  Drawer,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { api } from '../../api/client';
import { ExampleTag } from '../../components/ExampleTag';
import PendingStepCell from '../../components/PendingStepCell';
import type { PendingStep } from '../../components/PendingStepCell';
import { useT } from '../../i18n';
import { useAuthStore, hasPermission } from '../../stores/auth';
import { useEnums } from '../../i18n/enums';
import type { Member, ServiceItem, TicketPriority, TicketRow, TicketType } from '../../api/types';
import { PRIORITY_COLORS } from '../../api/types';

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
  service_item_id: number;
  assignee?: number;
  remarks?: string;
  change_type?: string;
  risk_level?: string;
  change_reason?: string;
  rollback_plan?: string;
  planned_window?: [Dayjs, Dayjs];
  implementation_plan?: string;
}

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
  const [members, setMembers] = useState<Member[]>([]);

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
    form.resetFields();
    setDrawerOpen(true);
    if (serviceItems.length === 0) {
      api
        .getList<ServiceItem>('/service-items')
        .then((res) => setServiceItems(res.items.filter((i) => i.status === '上架')))
        .catch(() => undefined);
    }
    if (members.length === 0) {
      api
        .getList<Member>('/members', { page: 1, page_size: 2000 })
        .then((res) => setMembers(res.items))
        .catch(() => undefined);
    }
  };

  const handleCreate = async () => {
    const values = await form.validateFields();
    const payload: Record<string, unknown> = {
      title: values.title,
      ticket_type: fixedType,
      priority: values.priority,
      description: values.description,
      service_item_id: values.service_item_id,
    };
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
      const created = await api.post<{ id: number }>('/tickets', payload);
      message.success(t('itsm.ticket.createdTyped', { type: et.ticketType(fixedType) }));
      setDrawerOpen(false);
      if (created?.id) {
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
        .getList<Member>('/members', { page: 1, page_size: 2000 })
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
    setEditSaving(true);
    try {
      await api.patch(`/tickets/${editing.id}`, {
        title: v.title,
        priority: v.priority,
        assignee: v.assignee ?? null,
        description: v.description,
        remarks: v.remarks,
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
    ...(canEdit || canDelete || fixedType === 'service_request' || isAdmin
      ? ([
          {
            title: t('common.actions'),
            key: 'actions',
            width: 150,
            fixed: 'right' as const,
            render: (_: unknown, r: TicketRow) =>
              r.is_example ? null : (
                <Space size={8}>
                  {canEdit && r.status !== 'closed' && r.status !== 'rejected' && (
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
                  {canDelete && (
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
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            {t('itsm.ticket.createTyped', { type: et.ticketType(fixedType) })}
          </Button>
        )
      }
    >
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
        onClose={() => setDrawerOpen(false)}
        destroyOnClose
        extra={
          <Space>
            <Button onClick={() => setDrawerOpen(false)}>{t('common.cancel')}</Button>
            <Button type="primary" loading={saving} onClick={() => void handleCreate()}>
              {t('common.submit')}
            </Button>
          </Space>
        }
      >
        <Form<TicketFormValues>
          form={form}
          layout="vertical"
          preserve={false}
          initialValues={{ priority: 'P3' }}
        >
          <Form.Item name="title" label={t('itsm.f.title')} rules={[{ required: true, message: t('itsm.rule.title') }]}>
            <Input maxLength={200} placeholder={t('itsm.ticket.titlePlaceholder')} />
          </Form.Item>
          <Form.Item name="priority" label={t('itsm.f.priority')} rules={[{ required: true, message: t('itsm.rule.priority') }]}>
            <Select
              options={(['P1', 'P2', 'P3', 'P4'] as TicketPriority[]).map((p) => ({
                value: p,
                label: p,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="description"
            label={t('itsm.f.description')}
            rules={[{ required: true, message: t('itsm.rule.description') }]}
          >
            <Input.TextArea rows={4} maxLength={2000} placeholder={t('itsm.ticket.descPlaceholder')} />
          </Form.Item>
          <Form.Item
            name="service_item_id"
            label={t('itsm.f.serviceItem')}
            rules={[{ required: true, message: t('itsm.rule.serviceItem') }]}
          >
            <Select
              showSearch
              optionFilterProp="label"
              placeholder={t('itsm.selectServiceItem')}
              options={serviceItems.map((i) => ({
                value: i.id,
                label: `${i.name}（${i.catalog_name ?? i.item_code}）`,
              }))}
            />
          </Form.Item>

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

          <Collapse
            ghost
            items={[
              {
                key: 'more',
                label: t('itsm.ticket.moreOptions'),
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
