import { useCallback, useEffect, useState } from 'react';
import { Button, Card, Form, Input, Modal, Select, Space, Table, Tag, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import { hasAnyRole, useAuthStore } from '../../stores/auth';
import type { Vendor, VendorRating } from '../../api/types';
import { VENDOR_RATING_COLORS } from '../../api/types';

interface VendorFormValues {
  name: string;
  contact?: string;
  phone?: string;
  email?: string;
  service_scope?: string;
  rating?: VendorRating;
  status?: '合作中' | '已终止';
  remarks?: string;
}

export default function Vendors() {
  const user = useAuthStore((s) => s.user);
  const canWrite = hasAnyRole(user, ['it_ops', 'cio', 'admin']);

  const [items, setItems] = useState<Vendor[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState('');

  const [editOpen, setEditOpen] = useState(false);
  const [editing, setEditing] = useState<Vendor | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<VendorFormValues>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<Vendor>('/vendors', {
        page,
        page_size: pageSize,
        q: q || undefined,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, q]);

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setEditOpen(true);
  };

  const openEdit = (row: Vendor) => {
    setEditing(row);
    form.resetFields();
    form.setFieldsValue({
      name: row.name,
      contact: row.contact ?? undefined,
      phone: row.phone ?? undefined,
      email: row.email ?? undefined,
      service_scope: row.service_scope ?? undefined,
      rating: row.rating ?? undefined,
      status: row.status,
      remarks: row.remarks ?? undefined,
    });
    setEditOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    const payload: Record<string, unknown> = {
      name: values.name,
      contact: values.contact ?? null,
      phone: values.phone ?? null,
      email: values.email ?? null,
      service_scope: values.service_scope ?? null,
      rating: values.rating ?? null,
      remarks: values.remarks ?? null,
    };
    setSaving(true);
    try {
      if (editing) {
        // 状态仅编辑时可改（后端创建接口不接收 status）
        payload.status = values.status;
        await api.patch(`/vendors/${editing.id}`, payload);
        message.success('供应商已更新');
      } else {
        await api.post('/vendors', payload);
        message.success('供应商已创建');
      }
      setEditOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const columns: ColumnsType<Vendor> = [
    { title: '编号', dataIndex: 'code', width: 120, fixed: 'left' },
    { title: '名称', dataIndex: 'name', width: 200, ellipsis: true },
    { title: '联系人', dataIndex: 'contact', width: 100, render: (v) => v || '-' },
    { title: '电话', dataIndex: 'phone', width: 130, render: (v) => v || '-' },
    { title: '邮箱', dataIndex: 'email', width: 180, ellipsis: true, render: (v) => v || '-' },
    { title: '服务范围', dataIndex: 'service_scope', width: 180, ellipsis: true, render: (v) => v || '-' },
    {
      title: '评级',
      dataIndex: 'rating',
      width: 80,
      render: (v: VendorRating | null) => (v ? <Tag color={VENDOR_RATING_COLORS[v]}>{v}</Tag> : '-'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: Vendor['status']) => <Tag color={v === '合作中' ? 'green' : 'default'}>{v}</Tag>,
    },
    { title: '合同数', dataIndex: 'contract_count', width: 80 },
    { title: 'CI 数', dataIndex: 'ci_count', width: 80 },
    ...(canWrite
      ? [
          {
            title: '操作',
            key: 'actions',
            width: 80,
            render: (_: unknown, r: Vendor) => (
              <Button type="link" size="small" onClick={() => openEdit(r)}>
                编辑
              </Button>
            ),
          } as ColumnsType<Vendor>[number],
        ]
      : []),
  ];

  return (
    <Card
      title="供应商"
      extra={
        canWrite && (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建供应商
          </Button>
        )
      }
    >
      <Space wrap style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="搜索名称"
          allowClear
          style={{ width: 220 }}
          onSearch={(v) => {
            setPage(1);
            setQ(v);
          }}
        />
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>
          刷新
        </Button>
      </Space>

      <Table<Vendor>
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

      <Modal
        title={editing ? `编辑供应商：${editing.code}` : '新建供应商'}
        open={editOpen}
        onOk={() => void handleSave()}
        confirmLoading={saving}
        onCancel={() => setEditOpen(false)}
        destroyOnClose
        width={560}
      >
        <Form<VendorFormValues> form={form} layout="vertical" preserve={false}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input maxLength={128} />
          </Form.Item>
          <Form.Item name="contact" label="联系人">
            <Input maxLength={64} />
          </Form.Item>
          <Form.Item name="phone" label="电话">
            <Input maxLength={32} />
          </Form.Item>
          <Form.Item name="email" label="邮箱" rules={[{ type: 'email', message: '邮箱格式不正确' }]}>
            <Input maxLength={128} />
          </Form.Item>
          <Form.Item name="service_scope" label="服务范围">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
          <Form.Item name="rating" label="评级">
            <Select
              allowClear
              options={(['A', 'B', 'C', 'D'] as VendorRating[]).map((r) => ({ value: r, label: r }))}
            />
          </Form.Item>
          {editing && (
            <Form.Item name="status" label="状态">
              <Select options={['合作中', '已终止'].map((s) => ({ value: s, label: s }))} />
            </Form.Item>
          )}
          <Form.Item name="remarks" label="备注">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
