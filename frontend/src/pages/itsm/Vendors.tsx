import { useCallback, useEffect, useState } from 'react';
import { Button, Card, Form, Input, Modal, Popconfirm, Select, Space, Tag, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import Table from '../../components/SortableTable';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import { ExampleTag } from '../../components/ExampleTag';
import ImportButtons from '../../components/ImportButtons';
import { hasAnyRole, hasPermission, useAuthStore } from '../../stores/auth';
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';
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
  const canDelete = hasPermission(user, 'vendors', 'delete'); // M21：默认矩阵仅 admin
  const isAdmin = !!user?.permissions?.['*'];
  const t = useT();
  const et = useEnums();

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
        message.success(t('itsm.vendor.updated'));
      } else {
        await api.post('/vendors', payload);
        message.success(t('itsm.vendor.created'));
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
    { title: t('itsm.f.code'), dataIndex: 'code', width: 140, fixed: 'left', onCell: () => ({ className: 'cell-nowrap' }) },
    {
      title: t('itsm.f.name'),
      dataIndex: 'name',
      width: 200,
      ellipsis: true,
      render: (v: string, r) => (
        <Space size={4}>
          {v}
          {r.is_example && <ExampleTag />}
        </Space>
      ),
    },
    { title: t('itsm.f.contact'), dataIndex: 'contact', width: 100, render: (v) => v || '-' },
    { title: t('itsm.f.phone'), dataIndex: 'phone', width: 130, onCell: () => ({ className: 'cell-nowrap' }), render: (v) => v || '-' },
    { title: t('itsm.f.email'), dataIndex: 'email', width: 180, ellipsis: true, render: (v) => v || '-' },
    { title: t('itsm.f.serviceScope'), dataIndex: 'service_scope', width: 180, ellipsis: true, render: (v) => v || '-' },
    {
      title: t('itsm.f.rating'),
      dataIndex: 'rating',
      width: 80,
      render: (v: VendorRating | null) => (v ? <Tag color={VENDOR_RATING_COLORS[v]}>{v}</Tag> : '-'),
    },
    {
      title: t('common.status'),
      dataIndex: 'status',
      width: 90,
      render: (v: Vendor['status']) => <Tag color={v === '合作中' ? 'green' : 'default'}>{et.vendorStatus(v)}</Tag>,
    },
    { title: t('itsm.vendor.contractCount'), dataIndex: 'contract_count', width: 80 },
    { title: t('itsm.vendor.ciCount'), dataIndex: 'ci_count', width: 80 },
    ...(canWrite || canDelete
      ? [
          {
            title: t('common.actions'),
            key: 'actions',
            width: 110,
            render: (_: unknown, r: Vendor) =>
              r.is_example && !isAdmin ? null : (
                <Space size={8}>
                  {canWrite && (
                    <Button type="link" size="small" style={{ padding: 0 }} onClick={() => openEdit(r)}>
                      {t('common.edit')}
                    </Button>
                  )}
                  {canDelete && (
                    <Popconfirm
                      title={t('common.deleteConfirm')}
                      onConfirm={async () => {
                        await api.delete(`/vendors/${r.id}`);
                        message.success(t('common.deleted'));
                        void load();
                      }}
                    >
                      <Button type="link" size="small" danger style={{ padding: 0 }}>
                        {t('common.delete')}
                      </Button>
                    </Popconfirm>
                  )}
                </Space>
              ),
          } as ColumnsType<Vendor>[number],
        ]
      : []),
  ];

  return (
    <Card
      title={t('itsm.vendor.title')}
      extra={
        canWrite && (
          <Space>
            <ImportButtons
              templateUrl="/itsm-import/vendor/template"
              importUrl="/itsm-import/vendor"
              onDone={() => void load()}
            />
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              {t('itsm.vendor.new')}
            </Button>
          </Space>
        )
      }
    >
      <Space wrap style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder={t('itsm.searchName')}
          allowClear
          style={{ width: 220 }}
          onSearch={(v) => {
            setPage(1);
            setQ(v);
          }}
        />
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>
          {t('common.refresh')}
        </Button>
      </Space>

      <Table<Vendor>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        standardToolbar={{ exportFileName: '供应商清单', showSearch: false, showFilter: false }}
        sticky
        scroll={{ x: 'max-content' }}
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
        title={editing ? t('itsm.vendor.edit', { code: editing.code }) : t('itsm.vendor.new')}
        open={editOpen}
        onOk={() => void handleSave()}
        confirmLoading={saving}
        onCancel={() => setEditOpen(false)}
        destroyOnClose
        width={560}
      >
        <Form<VendorFormValues> form={form} layout="vertical" preserve={false}>
          <Form.Item name="name" label={t('itsm.f.name')} rules={[{ required: true, message: t('itsm.rule.name') }]}>
            <Input maxLength={128} />
          </Form.Item>
          <Form.Item name="contact" label={t('itsm.f.contact')}>
            <Input maxLength={64} />
          </Form.Item>
          <Form.Item name="phone" label={t('itsm.f.phone')}>
            <Input maxLength={32} />
          </Form.Item>
          <Form.Item name="email" label={t('itsm.f.email')} rules={[{ type: 'email', message: t('itsm.vendor.emailInvalid') }]}>
            <Input maxLength={128} />
          </Form.Item>
          <Form.Item name="service_scope" label={t('itsm.f.serviceScope')}>
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
          <Form.Item name="rating" label={t('itsm.f.rating')}>
            <Select
              allowClear
              options={(['A', 'B', 'C', 'D'] as VendorRating[]).map((r) => ({ value: r, label: r }))}
            />
          </Form.Item>
          {editing && (
            <Form.Item name="status" label={t('common.status')}>
              <Select options={['合作中', '已终止'].map((s) => ({ value: s, label: et.vendorStatus(s) }))} />
            </Form.Item>
          )}
          <Form.Item name="remarks" label={t('common.remark')}>
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
