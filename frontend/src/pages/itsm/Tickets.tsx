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
  Radio,
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
import type { Member, ServiceItem, TicketPriority, TicketRow, TicketType } from '../../api/types';
import { PRIORITY_COLORS, TICKET_TYPE_COLORS, TICKET_TYPE_LABELS } from '../../api/types';

/** 状态 → Badge 样式（按语义猜测，未匹配用 processing） */
function statusBadge(status: string): 'default' | 'success' | 'error' | 'warning' | 'processing' {
  if (status === 'closed' || status === 'cancelled') return 'default';
  if (status === 'resolved' || status === 'approved') return 'success';
  if (status === 'rejected') return 'error';
  if (status === 'paused' || status === 'pending_approval') return 'warning';
  return 'processing';
}

/** SLA 达成状态渲染 */
export function renderSla(row: {
  sla_resolution_met: boolean | null;
  sla_warned: boolean;
}): JSX.Element | string {
  if (row.sla_resolution_met === true) return <Tag color="green">达成 ✓</Tag>;
  if (row.sla_resolution_met === false) return <Tag color="red">超时 ✗</Tag>;
  if (row.sla_warned) return <Tag color="orange">临期 ⚠</Tag>;
  return '-';
}

interface TicketFormValues {
  title: string;
  ticket_type: TicketType;
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

export default function Tickets() {
  const navigate = useNavigate();
  const [items, setItems] = useState<TicketRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);

  // 筛选
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<string | undefined>();
  const [ticketType, setTicketType] = useState<TicketType | undefined>();
  const [priority, setPriority] = useState<TicketPriority | undefined>();
  const [mineOnly, setMineOnly] = useState(false);
  // 状态筛选选项：从已加载数据中累积（code → 中文名）
  const [statusOptions, setStatusOptions] = useState<Record<string, string>>({});

  // 新建 Drawer
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<TicketFormValues>();
  const watchType = Form.useWatch('ticket_type', form);
  const [serviceItems, setServiceItems] = useState<ServiceItem[]>([]);
  const [members, setMembers] = useState<Member[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<TicketRow>('/tickets', {
        page,
        page_size: pageSize,
        q: q || undefined,
        status: status || undefined,
        ticket_type: ticketType || undefined,
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
  }, [page, pageSize, q, status, ticketType, priority, mineOnly]);

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
        .getList<Member>('/members', { page: 1, page_size: 999 })
        .then((res) => setMembers(res.items))
        .catch(() => undefined);
    }
  };

  const handleCreate = async () => {
    const values = await form.validateFields();
    const payload: Record<string, unknown> = {
      title: values.title,
      ticket_type: values.ticket_type,
      priority: values.priority,
      description: values.description,
      service_item_id: values.service_item_id,
    };
    if (values.assignee != null) payload.assignee = values.assignee;
    if (values.remarks) payload.remarks = values.remarks;
    if (values.ticket_type === 'change') {
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
      message.success('工单已创建');
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

  const columns: ColumnsType<TicketRow> = [
    {
      title: '编号',
      dataIndex: 'ticket_code',
      width: 140,
      fixed: 'left',
      render: (v: string, r) => <Link to={`/itsm/tickets/${r.id}`}>{v}</Link>,
    },
    { title: '标题', dataIndex: 'title', width: 220, ellipsis: true },
    {
      title: '类型',
      dataIndex: 'ticket_type',
      width: 100,
      render: (v: TicketType) => <Tag color={TICKET_TYPE_COLORS[v]}>{TICKET_TYPE_LABELS[v] ?? v}</Tag>,
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      width: 80,
      render: (v: TicketPriority) => <Tag color={PRIORITY_COLORS[v]}>{v}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status_name',
      width: 110,
      render: (v: string, r) => <Badge status={statusBadge(r.status)} text={v || r.status} />,
    },
    { title: '服务项', dataIndex: 'service_item_name', width: 150, ellipsis: true, render: (v) => v || '-' },
    { title: '受理人', dataIndex: 'assignee_name', width: 100, render: (v) => v || '-' },
    {
      title: '提交人',
      dataIndex: 'submitter_name',
      width: 120,
      render: (v: string | null, r) => (v ? `${v}${r.submitter_dept ? `(${r.submitter_dept})` : ''}` : '-'),
    },
    {
      title: '提交时间',
      dataIndex: 'submitted_at',
      width: 150,
      render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'),
    },
    { title: 'SLA', key: 'sla', width: 90, render: (_, r) => renderSla(r) },
  ];

  return (
    <Card
      title="工单"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建工单
        </Button>
      }
    >
      <Space wrap style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="搜索编号/标题"
          allowClear
          style={{ width: 220 }}
          onSearch={(v) => {
            setPage(1);
            setQ(v);
          }}
        />
        <Select
          placeholder="状态"
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
          placeholder="类型"
          allowClear
          style={{ width: 130 }}
          value={ticketType}
          onChange={(v) => {
            setPage(1);
            setTicketType(v);
          }}
          options={Object.entries(TICKET_TYPE_LABELS).map(([value, label]) => ({ value, label }))}
        />
        <Select
          placeholder="优先级"
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
          只看我的{' '}
          <Switch
            checked={mineOnly}
            onChange={(v) => {
              setPage(1);
              setMineOnly(v);
            }}
          />
        </span>
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>
          刷新
        </Button>
      </Space>

      <Table<TicketRow>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        scroll={{ x: 1300 }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
      />

      <Drawer
        title="新建工单"
        open={drawerOpen}
        width={560}
        onClose={() => setDrawerOpen(false)}
        destroyOnClose
        extra={
          <Space>
            <Button onClick={() => setDrawerOpen(false)}>取消</Button>
            <Button type="primary" loading={saving} onClick={() => void handleCreate()}>
              提交
            </Button>
          </Space>
        }
      >
        <Form<TicketFormValues>
          form={form}
          layout="vertical"
          preserve={false}
          initialValues={{ ticket_type: 'service_request', priority: 'P3' }}
        >
          <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input maxLength={200} placeholder="简要描述问题或请求" />
          </Form.Item>
          <Form.Item name="ticket_type" label="类型" rules={[{ required: true }]}>
            <Radio.Group>
              <Radio.Button value="service_request">服务请求</Radio.Button>
              <Radio.Button value="incident">事件</Radio.Button>
              <Radio.Button value="change">变更</Radio.Button>
            </Radio.Group>
          </Form.Item>
          <Form.Item name="priority" label="优先级" rules={[{ required: true, message: '请选择优先级' }]}>
            <Select
              options={(['P1', 'P2', 'P3', 'P4'] as TicketPriority[]).map((p) => ({
                value: p,
                label: p,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="description"
            label="描述"
            rules={[{ required: true, message: '请输入描述' }]}
          >
            <Input.TextArea rows={4} maxLength={2000} placeholder="详细描述背景、现象与期望" />
          </Form.Item>
          <Form.Item
            name="service_item_id"
            label="服务项"
            rules={[{ required: true, message: '请选择服务项' }]}
          >
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="选择关联的服务项"
              options={serviceItems.map((i) => ({
                value: i.id,
                label: `${i.name}（${i.catalog_name ?? i.item_code}）`,
              }))}
            />
          </Form.Item>

          {watchType === 'change' && (
            <Card size="small" title="变更信息" style={{ marginBottom: 16 }}>
              <Form.Item
                name="change_type"
                label="变更类型"
                rules={[{ required: true, message: '请选择变更类型' }]}
              >
                <Select
                  options={['标准', '普通', '紧急'].map((v) => ({ value: v, label: v }))}
                  placeholder="标准 / 普通 / 紧急"
                />
              </Form.Item>
              <Form.Item
                name="risk_level"
                label="风险等级"
                rules={[{ required: true, message: '请选择风险等级' }]}
              >
                <Select options={['高', '中', '低'].map((v) => ({ value: v, label: v }))} />
              </Form.Item>
              <Form.Item name="change_reason" label="变更原因">
                <Input.TextArea rows={2} maxLength={1000} />
              </Form.Item>
              <Form.Item name="rollback_plan" label="回退方案">
                <Input.TextArea rows={2} maxLength={1000} />
              </Form.Item>
              <Form.Item name="planned_window" label="变更窗口">
                <DatePicker.RangePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="implementation_plan" label="实施方案">
                <Input.TextArea rows={2} maxLength={2000} />
              </Form.Item>
            </Card>
          )}

          <Collapse
            ghost
            items={[
              {
                key: 'more',
                label: '更多选项',
                children: (
                  <>
                    <Form.Item name="assignee" label="受理人">
                      <Select
                        allowClear
                        showSearch
                        optionFilterProp="label"
                        placeholder="留空由后台分派"
                        options={members.map((m) => ({
                          value: m.id,
                          label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
                        }))}
                      />
                    </Form.Item>
                    <Form.Item name="remarks" label="备注">
                      <Input.TextArea rows={2} maxLength={500} />
                    </Form.Item>
                  </>
                ),
              },
            ]}
          />
        </Form>
      </Drawer>
    </Card>
  );
}
