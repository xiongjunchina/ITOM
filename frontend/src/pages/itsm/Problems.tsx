import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Badge, Button, Card, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from '../../api/client';
import { ExampleTag } from '../../components/ExampleTag';
import { hasPermission, useAuthStore } from '../../stores/auth';
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';
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
  assigned_line: string;
  service_item_id?: string;
  owner?: string;
}

export default function Problems() {
  const navigate = useNavigate();
  const t = useT();
  const et = useEnums();
  const user = useAuthStore((s) => s.user);
  const canDelete = hasPermission(user, 'problems', 'delete'); // M21：默认矩阵仅 admin
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
        assigned_line: values.assigned_line,
        service_item_id: values.service_item_id ?? undefined,
        owner: values.owner ?? undefined,
      });
      message.success(t('itsm.problem.created'));
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
      title: t('itsm.f.code'),
      dataIndex: 'problem_code',
      width: 140,
      fixed: 'left',
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (v: string, r) => (
        <Space size={4}>
          <Link to={`/itsm/problems/${r.id}`}>{v}</Link>
          {r.is_example && <ExampleTag />}
        </Space>
      ),
    },
    { title: t('itsm.f.title'), dataIndex: 'title', width: 260, ellipsis: true },
    {
      title: t('itsm.f.priority'),
      dataIndex: 'priority',
      width: 90,
      render: (v: TicketPriority) => <Tag color={PRIORITY_COLORS[v]}>{v}</Tag>,
    },
    {
      title: t('common.status'),
      dataIndex: 'status_name',
      width: 110,
      render: (v: string, r) => <Badge status={problemStatusBadge(r.status)} text={v || r.status} />,
    },
    { title: t('itsm.f.serviceItem'), dataIndex: 'service_item_name', width: 160, ellipsis: true, render: (v) => v || '-' },
    { title: t('itsm.f.owner'), dataIndex: 'owner_name', width: 100, render: (v) => v || '-' },
    { title: t('itsm.problem.linkedCount'), dataIndex: 'linked_ticket_count', width: 90 },
    {
      title: t('itsm.f.createdAt'),
      dataIndex: 'created_at',
      width: 150,
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'),
    },
    // M21：删除（delete 权限，默认仅 admin），示例数据只读
    ...(canDelete
      ? ([
          {
            title: t('common.actions'),
            key: 'actions',
            width: 70,
            fixed: 'right' as const,
            render: (_: unknown, r: ProblemRow) =>
              r.is_example ? null : (
                <Popconfirm
                  title={t('common.deleteConfirm')}
                  onConfirm={async () => {
                    await api.delete(`/problems/${r.id}`);
                    message.success(t('common.deleted'));
                    void load();
                  }}
                >
                  <Button type="link" size="small" danger style={{ padding: 0 }}>
                    {t('common.delete')}
                  </Button>
                </Popconfirm>
              ),
          },
        ] as ColumnsType<ProblemRow>)
      : []),
  ];

  return (
    <Card
      title={t('itsm.problem.title')}
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          {t('itsm.problem.new')}
        </Button>
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
          options={Object.keys(PROBLEM_STATUS_LABELS).map((value) => ({ value, label: et.problemStatus(value) }))}
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
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>
          {t('common.refresh')}
        </Button>
      </Space>

      <Table<ProblemRow>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        sticky
        scroll={{ x: 1100 }}
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

      <Modal
        title={t('itsm.problem.new')}
        open={createOpen}
        onOk={() => void handleCreate()}
        confirmLoading={saving}
        onCancel={() => setCreateOpen(false)}
        destroyOnClose
        width={560}
      >
        <Form<ProblemFormValues> form={form} layout="vertical" preserve={false} initialValues={{ priority: 'P3' }}>
          <Form.Item name="title" label={t('itsm.f.title')} rules={[{ required: true, message: t('itsm.rule.title') }]}>
            <Input maxLength={200} placeholder={t('itsm.problem.titlePlaceholder')} />
          </Form.Item>
          <Form.Item name="description" label={t('itsm.f.description')} rules={[{ required: true, message: t('itsm.rule.description') }]}>
            <Input.TextArea rows={4} maxLength={2000} placeholder={t('itsm.problem.descPlaceholder')} />
          </Form.Item>
          <Form.Item
            name="assigned_line"
            label={t('itsm.problem.line')}
            rules={[{ required: true, message: t('itsm.problem.lineRequired') }]}
            extra={t('itsm.problem.lineHint')}
          >
            <Select
              options={['product', 'ops', 'dev'].map((v) => ({ value: v, label: t('itsm.problem.line.' + v) }))}
              placeholder={t('itsm.problem.linePlaceholder')}
            />
          </Form.Item>
          <Form.Item name="priority" label={t('itsm.f.priority')} rules={[{ required: true, message: t('itsm.rule.priority') }]}>
            <Select
              options={(['P1', 'P2', 'P3', 'P4'] as TicketPriority[]).map((p) => ({ value: p, label: p }))}
            />
          </Form.Item>
          <Form.Item name="service_item_id" label={t('itsm.problem.serviceItemOptional')}>
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder={t('itsm.selectServiceItem')}
              options={serviceItems.map((i) => ({
                value: i.id,
                label: `${i.name}（${i.catalog_name ?? i.item_code}）`,
              }))}
            />
          </Form.Item>
          <Form.Item name="owner" label={t('itsm.problem.ownerOptional')}>
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder={t('itsm.ownerPlaceholder')}
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
