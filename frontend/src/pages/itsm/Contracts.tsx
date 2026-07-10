import { useCallback, useEffect, useState } from 'react';
import {
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined, ReloadOutlined, WarningOutlined } from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { api } from '../../api/client';
import { hasAnyRole, useAuthStore } from '../../stores/auth';
import type { Contract, ContractStatus, Member, Vendor } from '../../api/types';
import { CONTRACT_STATUS_COLORS } from '../../api/types';

interface ContractFormValues {
  name: string;
  vendor_id: string;
  period: [Dayjs, Dayjs];
  amount_10k?: number;
  owner?: string;
  remarks?: string;
}

export default function Contracts() {
  const user = useAuthStore((s) => s.user);
  const canWrite = hasAnyRole(user, ['it_ops', 'manager', 'admin']);

  const [items, setItems] = useState<Contract[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState('');
  const [vendorId, setVendorId] = useState<string | undefined>();

  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [members, setMembers] = useState<Member[]>([]);

  const [editOpen, setEditOpen] = useState(false);
  const [editing, setEditing] = useState<Contract | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<ContractFormValues>();

  useEffect(() => {
    api
      .getList<Vendor>('/vendors', { page: 1, page_size: 999 })
      .then((res) => setVendors(res.items))
      .catch(() => undefined);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<Contract>('/contracts', {
        page,
        page_size: pageSize,
        q: q || undefined,
        vendor_id: vendorId || undefined,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, q, vendorId]);

  useEffect(() => {
    void load();
  }, [load]);

  const ensureMembers = () => {
    if (members.length === 0) {
      api
        .getList<Member>('/members', { page: 1, page_size: 999 })
        .then((res) => setMembers(res.items))
        .catch(() => undefined);
    }
  };

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    if (vendorId) form.setFieldsValue({ vendor_id: vendorId });
    ensureMembers();
    setEditOpen(true);
  };

  const openEdit = (row: Contract) => {
    setEditing(row);
    form.resetFields();
    form.setFieldsValue({
      name: row.name,
      vendor_id: row.vendor_id,
      period: [dayjs(row.start_date), dayjs(row.end_date)],
      amount_10k: row.amount_10k ?? undefined,
      owner: row.owner ?? undefined,
      remarks: row.remarks ?? undefined,
    });
    ensureMembers();
    setEditOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    const payload: Record<string, unknown> = {
      name: values.name,
      vendor_id: values.vendor_id,
      start_date: values.period[0].format('YYYY-MM-DD'),
      end_date: values.period[1].format('YYYY-MM-DD'),
      amount_10k: values.amount_10k ?? null,
      owner: values.owner ?? null,
      remarks: values.remarks ?? null,
    };
    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/contracts/${editing.id}`, payload);
        message.success('合同已更新');
      } else {
        await api.post('/contracts', payload);
        message.success('合同已创建');
      }
      setEditOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const columns: ColumnsType<Contract> = [
    { title: '编号', dataIndex: 'code', width: 120, fixed: 'left' },
    { title: '名称', dataIndex: 'name', width: 220, ellipsis: true },
    { title: '供应商', dataIndex: 'vendor_name', width: 160, ellipsis: true, render: (v) => v || '-' },
    {
      title: '金额（万元）',
      dataIndex: 'amount_10k',
      width: 110,
      align: 'right',
      render: (v: number | null) => (v != null ? v.toLocaleString() : '-'),
    },
    { title: '开始日期', dataIndex: 'start_date', width: 110 },
    {
      title: '到期日期',
      dataIndex: 'end_date',
      width: 150,
      render: (v: string, r) => (
        <Space size={4}>
          {v}
          {r.days_to_expiry != null && r.days_to_expiry >= 0 && r.days_to_expiry <= 90 && (
            <Tooltip title={`${r.days_to_expiry} 天后到期`}>
              <WarningOutlined style={{ color: '#fa8c16' }} />
            </Tooltip>
          )}
        </Space>
      ),
    },
    {
      title: '剩余天数',
      dataIndex: 'days_to_expiry',
      width: 90,
      align: 'right',
      render: (v: number | null) => (v == null ? '-' : v < 0 ? `已过期 ${-v} 天` : `${v} 天`),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: ContractStatus) => <Tag color={CONTRACT_STATUS_COLORS[v] ?? 'default'}>{v}</Tag>,
    },
    { title: '负责人', dataIndex: 'owner_name', width: 100, render: (v) => v || '-' },
    ...(canWrite
      ? [
          {
            title: '操作',
            key: 'actions',
            width: 80,
            render: (_: unknown, r: Contract) => (
              <Button type="link" size="small" onClick={() => openEdit(r)}>
                编辑
              </Button>
            ),
          } as ColumnsType<Contract>[number],
        ]
      : []),
  ];

  return (
    <Card
      title="合同"
      extra={
        canWrite && (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建合同
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
        <Select
          placeholder="供应商"
          allowClear
          showSearch
          optionFilterProp="label"
          style={{ width: 200 }}
          value={vendorId}
          onChange={(v) => {
            setPage(1);
            setVendorId(v);
          }}
          options={vendors.map((v) => ({ value: v.id, label: v.name }))}
        />
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>
          刷新
        </Button>
      </Space>

      <Table<Contract>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        scroll={{ x: 1250 }}
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
        title={editing ? `编辑合同：${editing.code}` : '新建合同'}
        open={editOpen}
        onOk={() => void handleSave()}
        confirmLoading={saving}
        onCancel={() => setEditOpen(false)}
        destroyOnClose
        width={560}
      >
        <Form<ContractFormValues> form={form} layout="vertical" preserve={false}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="vendor_id" label="供应商" rules={[{ required: true, message: '请选择供应商' }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="选择供应商"
              options={vendors.map((v) => ({ value: v.id, label: v.name }))}
            />
          </Form.Item>
          <Form.Item name="period" label="合同期限" rules={[{ required: true, message: '请选择起止日期' }]}>
            <DatePicker.RangePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="amount_10k" label="金额（万元）">
            <InputNumber style={{ width: '100%' }} min={0} precision={2} />
          </Form.Item>
          <Form.Item name="owner" label="负责人">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="选择负责人"
              options={members.map((m) => ({
                value: m.id,
                label: m.dept ? `${m.name}（${m.dept}）` : m.name,
              }))}
            />
          </Form.Item>
          <Form.Item name="remarks" label="备注">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
