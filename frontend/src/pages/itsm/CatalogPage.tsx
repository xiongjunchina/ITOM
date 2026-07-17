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
  Popconfirm,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import { ExampleTag } from '../../components/ExampleTag';
import ImportButtons from '../../components/ImportButtons';
import { useAuthStore, hasAnyRole, hasPermission } from '../../stores/auth';
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';
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
  const canManage = hasAnyRole(user, ['admin', 'cio']);
  const canDelete = hasPermission(user, 'catalog', 'delete'); // M21：默认矩阵仅 admin
  const t = useT();
  const et = useEnums();

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
        .getList<Member>('/members', { page: 1, page_size: 2000 })
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
        message.success(t('itsm.catalog.updated'));
      } else {
        const { status: _status, ...createPayload } = values;
        await api.post('/catalogs', createPayload);
        message.success(t('itsm.catalog.created'));
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
        message.success(t('itsm.catalog.itemUpdated'));
      } else {
        const { status: _status, ...createPayload } = payload;
        await api.post('/service-items', createPayload);
        message.success(t('itsm.catalog.itemCreated'));
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
    { title: t('itsm.f.code'), dataIndex: 'item_code', width: 140, onCell: () => ({ className: 'cell-nowrap' }) },
    {
      title: t('itsm.f.name'),
      dataIndex: 'name',
      width: 180,
      ellipsis: true,
      render: (v: string, r) => (
        <Space size={4}>
          {v}
          {r.is_example && <ExampleTag />}
        </Space>
      ),
    },
    { title: t('itsm.f.type'), dataIndex: 'service_type', width: 110, render: (v) => v || '-' },
    { title: t('itsm.f.owner'), dataIndex: 'owner_name', width: 100, render: (v) => v || '-' },
    {
      title: t('itsm.catalog.slaCol'),
      key: 'sla',
      width: 140,
      render: (_, r) =>
        `${r.sla_response_hours ?? t('itsm.catalog.global')} / ${r.sla_resolution_hours ?? t('itsm.catalog.global')}`,
    },
    { title: t('itsm.f.targetAudience'), dataIndex: 'target_audience', width: 120, ellipsis: true, render: (v) => v || '-' },
    {
      title: t('common.status'),
      dataIndex: 'status',
      width: 80,
      render: (v: ServiceItem['status']) => (
        <Badge status={v === '上架' ? 'success' : 'default'} text={et.catalogStatus(v)} />
      ),
    },
    ...(canManage || canDelete
      ? [
          {
            title: t('common.actions'),
            key: 'action',
            width: 110,
            render: (_: unknown, record: ServiceItem) =>
              record.is_example ? null : (
                <Space size={8}>
                  {canManage && (
                    <Button type="link" size="small" style={{ padding: 0 }} onClick={() => openItemEdit(record)}>
                      {t('common.edit')}
                    </Button>
                  )}
                  {canDelete && (
                    <Popconfirm
                      title={t('common.deleteConfirm')}
                      onConfirm={async () => {
                        await api.delete(`/service-items/${record.id}`);
                        message.success(t('common.deleted'));
                        void loadItems();
                        void loadCatalogs();
                      }}
                    >
                      <Button type="link" size="small" danger style={{ padding: 0 }}>
                        {t('common.delete')}
                      </Button>
                    </Popconfirm>
                  )}
                </Space>
              ),
          } as ColumnsType<ServiceItem>[number],
        ]
      : []),
  ];

  return (
    <Row gutter={16}>
      <Col xs={24} md={8} lg={7} xl={6}>
        <Card
          title={t('itsm.catalog.title')}
          loading={catalogLoading}
          extra={
            canManage && (
              <Button type="primary" size="small" icon={<PlusOutlined />} onClick={openCatalogCreate}>
                {t('itsm.catalog.newCatalog')}
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
              <Typography.Text strong>{t('itsm.catalog.allItems')}</Typography.Text>
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
                      {c.is_example && <ExampleTag />}
                      <Tag color={TIER_COLORS[c.tier]}>{et.tier(c.tier)}</Tag>
                    </Space>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {c.code} · {t('itsm.catalog.itemCount', { n: c.item_count })}
                      {' · '}
                      <Badge status={c.status === '上架' ? 'success' : 'default'} text={et.catalogStatus(c.status)} />
                    </Typography.Text>
                  </Space>
                  <Space size={0}>
                    {canManage && !c.is_example && (
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
                    {canDelete && !c.is_example && (
                      <Popconfirm
                        title={t('common.deleteConfirm')}
                        onConfirm={async () => {
                          await api.delete(`/catalogs/${c.id}`);
                          message.success(t('common.deleted'));
                          if (selectedCatalog === c.id) setSelectedCatalog(null);
                          void loadCatalogs();
                        }}
                      >
                        <Button type="text" size="small" danger icon={<DeleteOutlined />} onClick={(e) => e.stopPropagation()} />
                      </Popconfirm>
                    )}
                  </Space>
                </Space>
              </Card>
            ))}
            {catalogs.length === 0 && !catalogLoading && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />}
          </Space>
        </Card>
      </Col>

      <Col xs={24} md={16} lg={17} xl={18}>
        <Card
          title={t('itsm.catalog.itemsTitle')}
          extra={
            <Space>
              <Input.Search
                placeholder={t('itsm.catalog.searchItem')}
                allowClear
                style={{ width: 200 }}
                onSearch={setQ}
              />
              {canManage && (
                <>
                  <ImportButtons
                    templateUrl="/itsm-import/catalog/template"
                    importUrl="/itsm-import/catalog"
                    onDone={() => {
                      void loadCatalogs();
                      void loadItems();
                    }}
                  />
                  <Button type="primary" icon={<PlusOutlined />} onClick={openItemCreate}>
                    {t('itsm.catalog.newItem')}
                  </Button>
                </>
              )}
            </Space>
          }
        >
          <Table<ServiceItem>
            rowKey="id"
            loading={itemLoading}
            columns={columns}
            dataSource={items}
            sticky
            scroll={{ x: 'max-content' }}
            pagination={{ pageSize: 20, showTotal: (n) => t('itsm.total', { n }) }}
          />
        </Card>
      </Col>

      {/* 目录 Modal */}
      <Modal
        title={editingCatalog ? t('itsm.catalog.editCatalog') : t('itsm.catalog.newCatalog')}
        open={catalogModalOpen}
        onOk={() => void saveCatalog()}
        confirmLoading={catalogSaving}
        onCancel={() => setCatalogModalOpen(false)}
        destroyOnClose
      >
        <Form<CatalogFormValues> form={catalogForm} layout="vertical" preserve={false}>
          <Form.Item name="name" label={t('itsm.f.name')} rules={[{ required: true, message: t('itsm.catalog.nameRequired') }]}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="tier" label={t('itsm.f.tier')} rules={[{ required: true, message: t('itsm.catalog.tierRequired') }]}>
            <Select
              options={(Object.keys(TIER_LABELS) as CatalogTier[]).map((tv) => ({
                value: tv,
                label: et.tier(tv),
              }))}
            />
          </Form.Item>
          <Form.Item name="description" label={t('itsm.f.description')}>
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
          <Form.Item name="sort" label={t('itsm.f.sort')}>
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          {editingCatalog && (
            <Form.Item name="status" label={t('common.status')}>
              <Select
                options={[
                  { value: '上架', label: et.catalogStatus('上架') },
                  { value: '下架', label: et.catalogStatus('下架') },
                ]}
              />
            </Form.Item>
          )}
        </Form>
      </Modal>

      {/* 服务项 Modal */}
      <Modal
        title={editingItem ? t('itsm.catalog.editItem') : t('itsm.catalog.newItem')}
        open={itemModalOpen}
        onOk={() => void saveItem()}
        confirmLoading={itemSaving}
        onCancel={() => setItemModalOpen(false)}
        destroyOnClose
        width={560}
      >
        <Form<ItemFormValues> form={itemForm} layout="vertical" preserve={false}>
          <Form.Item name="name" label={t('itsm.f.name')} rules={[{ required: true, message: t('itsm.catalog.itemNameRequired') }]}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item
            name="catalog_id"
            label={t('itsm.catalog.parentCatalog')}
            rules={[{ required: true, message: t('itsm.catalog.parentCatalogRequired') }]}
          >
            <Select
              showSearch
              optionFilterProp="label"
              options={catalogs.map((c) => ({ value: c.id, label: c.name }))}
            />
          </Form.Item>
          <Form.Item name="service_type" label={t('itsm.f.serviceType')}>
            <Input maxLength={50} placeholder={t('itsm.catalog.serviceTypePlaceholder')} />
          </Form.Item>
          <Form.Item name="owner" label={t('itsm.f.owner')}>
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
              label={t('itsm.catalog.slaResponseH')}
              style={{ width: '50%', marginRight: 8 }}
              extra={t('itsm.catalog.slaBlankHint')}
            >
              <InputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item
              name="sla_resolution_hours"
              label={t('itsm.catalog.slaResolutionH')}
              style={{ width: '50%' }}
              extra={t('itsm.catalog.slaBlankHint')}
            >
              <InputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="target_audience" label={t('itsm.f.targetAudience')}>
            <Input maxLength={100} placeholder={t('itsm.catalog.audiencePlaceholder')} />
          </Form.Item>
          <Form.Item name="description" label={t('itsm.f.description')}>
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
          {editingItem && (
            <Form.Item name="status" label={t('common.status')}>
              <Select
                options={[
                  { value: '上架', label: et.catalogStatus('上架') },
                  { value: '下架', label: et.catalogStatus('下架') },
                ]}
              />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </Row>
  );
}
