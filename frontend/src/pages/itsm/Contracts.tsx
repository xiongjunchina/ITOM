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
import { ExampleTag } from '../../components/ExampleTag';
import ImportButtons from '../../components/ImportButtons';
import { hasAnyRole, useAuthStore } from '../../stores/auth';
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';
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
  const canWrite = hasAnyRole(user, ['it_ops', 'cio', 'admin']);
  const t = useT();
  const et = useEnums();

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
        message.success(t('itsm.contract.updated'));
      } else {
        await api.post('/contracts', payload);
        message.success(t('itsm.contract.created'));
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
    { title: t('itsm.f.code'), dataIndex: 'code', width: 140, fixed: 'left', onCell: () => ({ className: 'cell-nowrap' }) },
    {
      title: t('itsm.f.name'),
      dataIndex: 'name',
      width: 220,
      ellipsis: true,
      render: (v: string, r) => (
        <Space size={4}>
          {v}
          {r.is_example && <ExampleTag />}
        </Space>
      ),
    },
    { title: t('itsm.f.vendor'), dataIndex: 'vendor_name', width: 160, ellipsis: true, render: (v) => v || '-' },
    {
      title: t('itsm.contract.amount'),
      dataIndex: 'amount_10k',
      width: 110,
      align: 'right',
      render: (v: number | null) => (v != null ? v.toLocaleString() : '-'),
    },
    { title: t('itsm.f.startDate'), dataIndex: 'start_date', width: 110, onCell: () => ({ className: 'cell-nowrap' }) },
    {
      title: t('itsm.f.endDate'),
      dataIndex: 'end_date',
      width: 150,
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (v: string, r) => (
        <Space size={4}>
          {v}
          {r.days_to_expiry != null && r.days_to_expiry >= 0 && r.days_to_expiry <= 90 && (
            <Tooltip title={t('itsm.contract.expiresIn', { n: r.days_to_expiry })}>
              <WarningOutlined style={{ color: '#fa8c16' }} />
            </Tooltip>
          )}
        </Space>
      ),
    },
    {
      title: t('itsm.contract.daysLeft'),
      dataIndex: 'days_to_expiry',
      width: 130,
      align: 'right',
      render: (v: number | null) =>
        v == null ? '-' : v < 0 ? t('itsm.contract.expiredDays', { n: -v }) : t('itsm.unit.days', { n: v }),
    },
    {
      title: t('common.status'),
      dataIndex: 'status',
      width: 90,
      render: (v: ContractStatus) => <Tag color={CONTRACT_STATUS_COLORS[v] ?? 'default'}>{et.contractStatus(v)}</Tag>,
    },
    { title: t('itsm.f.owner'), dataIndex: 'owner_name', width: 100, render: (v) => v || '-' },
    ...(canWrite
      ? [
          {
            title: t('common.actions'),
            key: 'actions',
            width: 80,
            render: (_: unknown, r: Contract) =>
              r.is_example ? null : (
                <Button type="link" size="small" onClick={() => openEdit(r)}>
                  {t('common.edit')}
                </Button>
              ),
          } as ColumnsType<Contract>[number],
        ]
      : []),
  ];

  return (
    <Card
      title={t('itsm.contract.title')}
      extra={
        canWrite && (
          <Space>
            <ImportButtons
              templateUrl="/itsm-import/contract/template"
              importUrl="/itsm-import/contract"
              onDone={() => void load()}
            />
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              {t('itsm.contract.new')}
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
        <Select
          placeholder={t('itsm.f.vendor')}
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
          {t('common.refresh')}
        </Button>
      </Space>

      <Table<Contract>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
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
        title={editing ? t('itsm.contract.edit', { code: editing.code }) : t('itsm.contract.new')}
        open={editOpen}
        onOk={() => void handleSave()}
        confirmLoading={saving}
        onCancel={() => setEditOpen(false)}
        destroyOnClose
        width={560}
      >
        <Form<ContractFormValues> form={form} layout="vertical" preserve={false}>
          <Form.Item name="name" label={t('itsm.f.name')} rules={[{ required: true, message: t('itsm.rule.name') }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="vendor_id" label={t('itsm.f.vendor')} rules={[{ required: true, message: t('itsm.contract.vendorRequired') }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder={t('itsm.selectVendor')}
              options={vendors.map((v) => ({ value: v.id, label: v.name }))}
            />
          </Form.Item>
          <Form.Item name="period" label={t('itsm.contract.period')} rules={[{ required: true, message: t('itsm.contract.periodRequired') }]}>
            <DatePicker.RangePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="amount_10k" label={t('itsm.contract.amount')}>
            <InputNumber style={{ width: '100%' }} min={0} precision={2} />
          </Form.Item>
          <Form.Item name="owner" label={t('itsm.f.owner')}>
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
          <Form.Item name="remarks" label={t('common.remark')}>
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
