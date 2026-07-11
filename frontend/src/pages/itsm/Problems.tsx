import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Badge, Button, Card, Form, Input, Modal, Select, Space, Table, Tag, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from '../../api/client';
import type { Member, ProblemRow, ServiceItem, TicketPriority } from '../../api/types';
import { PRIORITY_COLORS, PROBLEM_STATUS_LABELS } from '../../api/types';

export function problemStatusBadge(
  status: string,
): 'default' | 'success' | 'error' | 'warning' | 'processing' {
  if (status === 'closed') return 'default';
  if (status === 'resolved') return 'success';
  if (status === 'known_error') return 'warning';
  return 'processing';
}

interface ProblemFormValues {
  title: string;
  description: string;
  priority: TicketPriority;
  service_item_id?: string;
  owner?: string;
}

export default function Problems() {
  const navigate = useNavigate();
  const [items, setItems] = useState<ProblemRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);

  // 筛选
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<string | undefined>();
  const [priority, setPriority] = useState<TicketPriority | undefined>();

  // 新建 Modal
  const [createOpen, setCreateOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<ProblemFormValues>();
  const [serviceItems, setServiceItems] = useState<ServiceItem[]>([]);
  const [members, setMembers] = useState<Member[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<ProblemRow>('/problems', {
        page,
        page_size: pageSize,
        q: q || undefined,
        status: status || undefined,
        priority: priority || undefined,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, q, status, priority]);

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = () => {
    form.resetFields();
    setCreateOpen(true);
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
    setSaving(true);
    try {
      const created = await api.post<ProblemRow>('/problems', {
        title: values.title,
        description: values.description,
        priority: values.priority,
        service_item_id: values.service_item_id ?? undefined,
        owner: values.owner ?? undefined,
      });
      message.success('问题已创建');
      setCreateOpen(false);
      if (created?.id) {
        navigate(`/itsm/problems/${created.id}`);
      } else {
        void load();
      }
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const columns: ColumnsType<ProblemRow> = [
    {
      title: '编号',
      dataIndex: 'problem_code',
      width: 140,
      fixed: 'left',
      render: (v: string, r) => <Link to={`/itsm/problems/${r.id}`}>{v}</Link>,
    },
    { title: '标题', dataIndex: 'title', width: 260, ellipsis: true },
    {
      title: '优先级',
      dataIndex: 'priority',
      width: 90,
      render: (v: TicketPriority) => <Tag color={PRIORITY_COLORS[v]}>{v}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status_name',
      width: 110,
      render: (v: string, r) => <Badge status={problemStatusBadge(r.status)} text={v || r.status} />,
    },
    { title: '服务项', dataIndex: 'service_item_name', width: 160, ellipsis: true, render: (v) => v || '-' },
    { title: '负责人', dataIndex: 'owner_name', width: 100, render: (v) => v || '-' },
    { title: '关联工单', dataIndex: 'linked_ticket_count', width: 90 },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 150,
      render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'),
    },
  ];

  return (
    <Card
      title="问题管理"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建问题
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
          options={Object.entries(PROBLEM_STATUS_LABELS).map(([value, label]) => ({ value, label }))}
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
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>
          刷新
        </Button>
      </Space>

      <Table<ProblemRow>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        scroll={{ x: 1100 }}
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

      <Modal
        title="新建问题"
        open={createOpen}
        onOk={() => void handleCreate()}
        confirmLoading={saving}
        onCancel={() => setCreateOpen(false)}
        destroyOnClose
        width={560}
      >
        <Form<ProblemFormValues> form={form} layout="vertical" preserve={false} initialValues={{ priority: 'P3' }}>
          <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input maxLength={200} placeholder="简要描述问题" />
          </Form.Item>
          <Form.Item name="description" label="描述" rules={[{ required: true, message: '请输入描述' }]}>
            <Input.TextArea rows={4} maxLength={2000} placeholder="问题现象、影响范围与已知信息" />
          </Form.Item>
          <Form.Item name="priority" label="优先级" rules={[{ required: true, message: '请选择优先级' }]}>
            <Select
              options={(['P1', 'P2', 'P3', 'P4'] as TicketPriority[]).map((p) => ({ value: p, label: p }))}
            />
          </Form.Item>
          <Form.Item name="service_item_id" label="服务项（可选）">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="选择关联的服务项"
              options={serviceItems.map((i) => ({
                value: i.id,
                label: `${i.name}（${i.catalog_name ?? i.item_code}）`,
              }))}
            />
          </Form.Item>
          <Form.Item name="owner" label="负责人（可选）">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="选择负责人"
              options={members.map((m) => ({
                value: m.id,
                label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
              }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
