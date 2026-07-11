import { useCallback, useEffect, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { EditOutlined, PlusOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import { useAuthStore, hasAnyRole } from '../../stores/auth';
import type { Catalog, CatalogTier, Member, ServiceItem } from '../../api/types';
import { TIER_COLORS, TIER_LABELS } from '../../api/types';

interface CatalogFormValues {
  name: string;
  tier: CatalogTier;
  description?: string;
  sort?: number;
  status?: '上架' | '下架';
}

interface ItemFormValues {
  name: string;
  catalog_id: string;
  service_type?: string;
  owner?: string;
  description?: string;
  sla_response_hours?: number | null;
  sla_resolution_hours?: number | null;
  target_audience?: string;
  status?: '上架' | '下架';
}

export default function CatalogPage() {
  const user = useAuthStore((s) => s.user);
  const canManage = hasAnyRole(user, ['admin', 'manager']);

  const [catalogs, setCatalogs] = useState<Catalog[]>([]);
  const [selectedCatalog, setSelectedCatalog] = useState<string | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false);

  const [items, setItems] = useState<ServiceItem[]>([]);
  const [itemLoading, setItemLoading] = useState(false);
  const [q, setQ] = useState('');

  const [members, setMembers] = useState<Member[]>([]);

  // 目录 Modal
  const [catalogModalOpen, setCatalogModalOpen] = useState(false);
  const [editingCatalog, setEditingCatalog] = useState<Catalog | null>(null);
  const [catalogSaving, setCatalogSaving] = useState(false);
  const [catalogForm] = Form.useForm<CatalogFormValues>();

  // 服务项 Modal
  const [itemModalOpen, setItemModalOpen] = useState(false);
  const [editingItem, setEditingItem] = useState<ServiceItem | null>(null);
  const [itemSaving, setItemSaving] = useState(false);
  const [itemForm] = Form.useForm<ItemFormValues>();

  const loadCatalogs = useCallback(async () => {
    setCatalogLoading(true);
    try {
      const res = await api.getList<Catalog>('/catalogs');
      setCatalogs(res.items);
    } catch {
      // 已统一提示
    } finally {
      setCatalogLoading(false);
    }
  }, []);

  const loadItems = useCallback(async () => {
    setItemLoading(true);
    try {
      const res = await api.getList<ServiceItem>('/service-items', {
        catalog_id: selectedCatalog ?? undefined,
        q: q || undefined,
      });
      setItems(res.items);
    } catch {
      // 已统一提示
    } finally {
      setItemLoading(false);
    }
  }, [selectedCatalog, q]);

  useEffect(() => {
    void loadCatalogs();
  }, [loadCatalogs]);

  useEffect(() => {
    void loadItems();
  }, [loadItems]);

  useEffect(() => {
    if (canManage) {
      api
        .getList<Member>('/members', { page: 1, page_size: 999 })
        .then((res) => setMembers(res.items))
        .catch(() => undefined);
    }
  }, [canManage]);

  // ---- 目录增改 ----
  const openCatalogCreate = () => {
    setEditingCatalog(null);
    catalogForm.resetFields();
    setCatalogModalOpen(true);
  };

  const openCatalogEdit = (c: Catalog) => {
    setEditingCatalog(c);
    catalogForm.setFieldsValue({
      name: c.name,
      tier: c.tier,
      description: c.description ?? undefined,
      sort: c.sort ?? undefined,
      status: c.status,
    });
    setCatalogModalOpen(true);
  };

  const saveCatalog = async () => {
    const values = await catalogForm.validateFields();
    setCatalogSaving(true);
    try {
      if (editingCatalog) {
        await api.patch(`/catalogs/${editingCatalog.id}`, values);
        message.success('目录已更新');
      } else {
        const { status: _status, ...createPayload } = values;
        await api.post('/catalogs', createPayload);
        message.success('目录已创建');
      }
      setCatalogModalOpen(false);
      void loadCatalogs();
    } catch {
      // 已统一提示
    } finally {
      setCatalogSaving(false);
    }
  };

  // ---- 服务项增改 ----
  const openItemCreate = () => {
    setEditingItem(null);
    itemForm.resetFields();
    if (selectedCatalog != null) itemForm.setFieldsValue({ catalog_id: selectedCatalog });
    setItemModalOpen(true);
  };

  const openItemEdit = (it: ServiceItem) => {
    setEditingItem(it);
    itemForm.setFieldsValue({
      name: it.name,
      catalog_id: it.catalog_id,
      service_type: it.service_type ?? undefined,
      owner: it.owner ?? undefined,
      description: it.description ?? undefined,
      sla_response_hours: it.sla_response_hours ?? undefined,
      sla_resolution_hours: it.sla_resolution_hours ?? undefined,
      target_audience: it.target_audience ?? undefined,
      status: it.status,
    });
    setItemModalOpen(true);
  };

  const saveItem = async () => {
    const values = await itemForm.validateFields();
    const payload = {
      ...values,
      sla_response_hours: values.sla_response_hours ?? null,
      sla_resolution_hours: values.sla_resolution_hours ?? null,
    };
    setItemSaving(true);
    try {
      if (editingItem) {
        await api.patch(`/service-items/${editingItem.id}`, payload);
        message.success('服务项已更新');
      } else {
        const { status: _status, ...createPayload } = payload;
        await api.post('/service-items', createPayload);
        message.success('服务项已创建');
      }
      setItemModalOpen(false);
      void loadItems();
      void loadCatalogs(); // item_count 变化
    } catch {
      // 已统一提示
    } finally {
      setItemSaving(false);
    }
  };

  const columns: ColumnsType<ServiceItem> = [
    { title: '编号', dataIndex: 'item_code', width: 120 },
    { title: '名称', dataIndex: 'name', width: 180, ellipsis: true },
    { title: '类型', dataIndex: 'service_type', width: 110, render: (v) => v || '-' },
    { title: '负责人', dataIndex: 'owner_name', width: 100, render: (v) => v || '-' },
    {
      title: 'SLA(响应h/解决h)',
      key: 'sla',
      width: 140,
      render: (_, r) =>
        `${r.sla_response_hours ?? '全局'} / ${r.sla_resolution_hours ?? '全局'}`,
    },
    { title: '服务对象', dataIndex: 'target_audience', width: 120, ellipsis: true, render: (v) => v || '-' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      render: (v: ServiceItem['status']) => (
        <Badge status={v === '上架' ? 'success' : 'default'} text={v} />
      ),
    },
    ...(canManage
      ? [
          {
            title: '操作',
            key: 'action',
            width: 80,
            render: (_: unknown, record: ServiceItem) => (
              <Button type="link" size="small" onClick={() => openItemEdit(record)}>
                编辑
              </Button>
            ),
          } as ColumnsType<ServiceItem>[number],
        ]
      : []),
  ];

  return (
    <Row gutter={16}>
      <Col xs={24} md={8} lg={7} xl={6}>
        <Card
          title="服务目录"
          loading={catalogLoading}
          extra={
            canManage && (
              <Button type="primary" size="small" icon={<PlusOutlined />} onClick={openCatalogCreate}>
                新建目录
              </Button>
            )
          }
        >
          <Space direction="vertical" style={{ width: '100%' }} size={8}>
            <Card
              size="small"
              hoverable
              onClick={() => setSelectedCatalog(null)}
              style={selectedCatalog === null ? { borderColor: '#1677ff' } : undefined}
            >
              <Typography.Text strong>全部服务项</Typography.Text>
            </Card>
            {catalogs.map((c) => (
              <Card
                key={c.id}
                size="small"
                hoverable
                onClick={() => setSelectedCatalog(c.id)}
                style={selectedCatalog === c.id ? { borderColor: '#1677ff' } : undefined}
              >
                <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                  <Space direction="vertical" size={2}>
                    <Space size={6}>
                      <Typography.Text strong>{c.name}</Typography.Text>
                      <Tag color={TIER_COLORS[c.tier]}>{TIER_LABELS[c.tier] ?? c.tier}</Tag>
                    </Space>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {c.code} · {c.item_count} 个服务项
                      {' · '}
                      <Badge status={c.status === '上架' ? 'success' : 'default'} text={c.status} />
                    </Typography.Text>
                  </Space>
                  {canManage && (
                    <Button
                      type="text"
                      size="small"
                      icon={<EditOutlined />}
                      onClick={(e) => {
                        e.stopPropagation();
                        openCatalogEdit(c);
                      }}
                    />
                  )}
                </Space>
              </Card>
            ))}
            {catalogs.length === 0 && !catalogLoading && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />}
          </Space>
        </Card>
      </Col>

      <Col xs={24} md={16} lg={17} xl={18}>
        <Card
          title="服务项"
          extra={
            <Space>
              <Input.Search
                placeholder="搜索服务项"
                allowClear
                style={{ width: 200 }}
                onSearch={setQ}
              />
              {canManage && (
                <Button type="primary" icon={<PlusOutlined />} onClick={openItemCreate}>
                  新建服务项
                </Button>
              )}
            </Space>
          }
        >
          <Table<ServiceItem>
            rowKey="id"
            loading={itemLoading}
            columns={columns}
            dataSource={items}
            scroll={{ x: 900 }}
            pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
          />
        </Card>
      </Col>

      {/* 目录 Modal */}
      <Modal
        title={editingCatalog ? '编辑目录' : '新建目录'}
        open={catalogModalOpen}
        onOk={() => void saveCatalog()}
        confirmLoading={catalogSaving}
        onCancel={() => setCatalogModalOpen(false)}
        destroyOnClose
      >
        <Form<CatalogFormValues> form={catalogForm} layout="vertical" preserve={false}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入目录名称' }]}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="tier" label="等级" rules={[{ required: true, message: '请选择等级' }]}>
            <Select
              options={(Object.keys(TIER_LABELS) as CatalogTier[]).map((t) => ({
                value: t,
                label: TIER_LABELS[t],
              }))}
            />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
          <Form.Item name="sort" label="排序">
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          {editingCatalog && (
            <Form.Item name="status" label="状态">
              <Select
                options={[
                  { value: '上架', label: '上架' },
                  { value: '下架', label: '下架' },
                ]}
              />
            </Form.Item>
          )}
        </Form>
      </Modal>

      {/* 服务项 Modal */}
      <Modal
        title={editingItem ? '编辑服务项' : '新建服务项'}
        open={itemModalOpen}
        onOk={() => void saveItem()}
        confirmLoading={itemSaving}
        onCancel={() => setItemModalOpen(false)}
        destroyOnClose
        width={560}
      >
        <Form<ItemFormValues> form={itemForm} layout="vertical" preserve={false}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入服务项名称' }]}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item
            name="catalog_id"
            label="所属目录"
            rules={[{ required: true, message: '请选择所属目录' }]}
          >
            <Select
              showSearch
              optionFilterProp="label"
              options={catalogs.map((c) => ({ value: c.id, label: c.name }))}
            />
          </Form.Item>
          <Form.Item name="service_type" label="服务类型">
            <Input maxLength={50} placeholder="如：账号权限 / 软硬件 / 咨询" />
          </Form.Item>
          <Form.Item name="owner" label="负责人">
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
          <Space.Compact block>
            <Form.Item
              name="sla_response_hours"
              label="SLA 响应(小时)"
              style={{ width: '50%', marginRight: 8 }}
              extra="留空 = 使用全局策略"
            >
              <InputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item
              name="sla_resolution_hours"
              label="SLA 解决(小时)"
              style={{ width: '50%' }}
              extra="留空 = 使用全局策略"
            >
              <InputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="target_audience" label="服务对象">
            <Input maxLength={100} placeholder="如：全体员工 / 研发团队" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
          {editingItem && (
            <Form.Item name="status" label="状态">
              <Select
                options={[
                  { value: '上架', label: '上架' },
                  { value: '下架', label: '下架' },
                ]}
              />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </Row>
  );
}
