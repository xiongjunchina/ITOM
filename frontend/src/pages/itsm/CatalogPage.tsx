import { useCallback, useEffect, useMemo, useState } from 'react';
import type { Key } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  Alert,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Tag,
  Tree,
  Tooltip,
  Typography,
  message,
  Popconfirm,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { DataNode } from 'antd/es/tree';
import { useNavigate } from 'react-router-dom';
import {
  ArrowDownOutlined,
  ArrowLeftOutlined,
  ArrowRightOutlined,
  ArrowUpOutlined,
  ApartmentOutlined,
  CustomerServiceOutlined,
  DeleteOutlined,
  EditOutlined,
  FilterOutlined,
  KeyOutlined,
  PlusOutlined,
  ReadOutlined,
  RightOutlined,
  SearchOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { api } from '../../api/client';
import { ExampleTag } from '../../components/ExampleTag';
import ImportButtons from '../../components/ImportButtons';
import { useAuthStore, hasAnyRole, hasPermission } from '../../stores/auth';
import { isRequesterOnly } from '../../components/menu';
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';
import type { Catalog, CatalogTier, Department, Member, ServiceItem } from '../../api/types';
import { TIER_COLORS, TIER_LABELS } from '../../api/types';
import SortableTable from '../../components/SortableTable';

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
  target_audience_mode?: 'all' | 'custom';
  status?: '上架' | '下架';
}

type AudienceRef = { type: 'department' | 'member'; id: string };

export default function CatalogPage() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const requesterPortal = isRequesterOnly(user);
  const canManage = hasAnyRole(user, ['admin', 'cio']);
  const canDelete = hasPermission(user, 'catalog', 'delete'); // M21：默认矩阵仅 admin
  const isAdmin = !!user?.permissions?.['*'];
  const t = useT();
  const et = useEnums();

  const [catalogs, setCatalogs] = useState<Catalog[]>([]);
  const [selectedCatalog, setSelectedCatalog] = useState<string | null>(null);
  const [catalogHistory, setCatalogHistory] = useState<Array<string | null>>([null]);
  const [catalogHistoryIndex, setCatalogHistoryIndex] = useState(0);
  const [catalogLoading, setCatalogLoading] = useState(false);

  const [items, setItems] = useState<ServiceItem[]>([]);
  const [itemLoading, setItemLoading] = useState(false);
  const [itemPage, setItemPage] = useState(1);
  const [itemPageSize, setItemPageSize] = useState(20);
  const [q, setQ] = useState('');
  const [itemStatus, setItemStatus] = useState<'全部' | '上架' | '下架'>('全部');

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

  // 服务对象范围选择器：结构化保存部门/员工引用，兼容旧版 target_audience 文本。
  const [audienceMode, setAudienceMode] = useState<'all' | 'custom'>('all');
  const [audienceRefs, setAudienceRefs] = useState<AudienceRef[]>([]);
  const [audienceDraftRefs, setAudienceDraftRefs] = useState<AudienceRef[]>([]);
  const [audienceDepartments, setAudienceDepartments] = useState<Department[]>([]);
  const [audienceMembers, setAudienceMembers] = useState<Member[]>([]);
  const [audienceModalOpen, setAudienceModalOpen] = useState(false);
  const [audienceLoading, setAudienceLoading] = useState(false);

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
        status: itemStatus === '全部' ? undefined : itemStatus,
      });
      setItems(res.items);
    } catch {
      // 已统一提示
    } finally {
      setItemLoading(false);
    }
  }, [selectedCatalog, q, itemStatus]);

  const loadAudienceOptions = useCallback(async () => {
    setAudienceLoading(true);
    try {
      const [departmentRes, memberRes] = await Promise.all([
        api.getList<Department>('/admin/departments'),
        api.getList<Member>('/members', { page: 1, page_size: 2000 }),
      ]);
      setAudienceDepartments(departmentRes.items.filter((department) => department.active));
      setAudienceMembers(memberRes.items.filter((member) => member.status !== '离职'));
    } catch {
      // 已统一提示
    } finally {
      setAudienceLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCatalogs();
  }, [loadCatalogs]);

  useEffect(() => {
    void loadItems();
  }, [loadItems]);

  useEffect(() => {
    setItemPage(1);
  }, [selectedCatalog, q, itemStatus]);

  useEffect(() => {
    if (canManage) {
      api
        .getList<Member>('/members', { page: 1, page_size: 2000, scope: 'it' })
        .then((res) => setMembers(res.items))
        .catch(() => undefined);
    }
  }, [canManage]);

  const audienceTreeData = useMemo<DataNode[]>(() => {
    const activeDepartments = audienceDepartments.filter((department) => department.active);
    const membersByDepartment = new Map<string, Member[]>();
    const unassignedMembers: Member[] = [];
    audienceMembers.forEach((member) => {
      if (member.department_id) {
        const current = membersByDepartment.get(member.department_id) ?? [];
        current.push(member);
        membersByDepartment.set(member.department_id, current);
      } else {
        unassignedMembers.push(member);
      }
    });
    const departmentByParent = new Map<string | null, Department[]>();
    activeDepartments.forEach((department) => {
      const current = departmentByParent.get(department.parent_id) ?? [];
      current.push(department);
      departmentByParent.set(department.parent_id, current);
    });
    const memberNode = (member: Member): DataNode => ({
      key: `audience-member:${member.id}`,
      title: <Space size={6}><UserOutlined />{member.name}{member.employee_no ? `（${member.employee_no}）` : ''}</Space>,
      isLeaf: true,
    });
    const building = (parentId: string | null, trail = new Set<string>()): DataNode[] =>
      (departmentByParent.get(parentId) ?? [])
        .filter((department) => !trail.has(department.id))
        .map((department) => {
          const nextTrail = new Set(trail).add(department.id);
          const children = [
            ...building(department.id, nextTrail),
            ...(membersByDepartment.get(department.id) ?? []).map(memberNode),
          ];
          return {
            key: `audience-department:${department.id}`,
            title: <Space size={6}><ApartmentOutlined />{department.name}</Space>,
            children,
          };
        });
    const rootChildren = building(null);
    if (unassignedMembers.length > 0) {
      rootChildren.push({
        key: 'audience-unassigned',
        title: '未归属部门人员',
        disableCheckbox: true,
        children: unassignedMembers.map(memberNode),
      });
    }
    return [{
      key: 'audience-root',
      title: '公司组织架构',
      disableCheckbox: true,
      children: rootChildren,
    }];
  }, [audienceDepartments, audienceMembers]);

  const audienceLabels = useMemo(() => {
    const labels = new Map<string, string>();
    audienceDepartments.forEach((department) => labels.set(`department:${department.id}`, `部门：${department.name}`));
    audienceMembers.forEach((member) => labels.set(`member:${member.id}`, `员工：${member.name}`));
    return labels;
  }, [audienceDepartments, audienceMembers]);

  const audienceSummary = audienceMode === 'all'
    ? t('itsm.catalog.allEmployees')
    : audienceRefs.map((ref) => audienceLabels.get(`${ref.type}:${ref.id}`) ?? `${ref.type === 'department' ? '部门' : '员工'}：${ref.id}`).join('、')
      || t('itsm.catalog.selectAudience');

  const parseAudienceKeys = (keys: Key[]): AudienceRef[] => keys.flatMap((key): AudienceRef[] => {
    const [kind, id] = String(key).split(':');
    if (kind === 'audience-department' && id) return [{ type: 'department' as const, id }];
    if (kind === 'audience-member' && id) return [{ type: 'member' as const, id }];
    return [];
  });

  const openAudienceSelector = async () => {
    setAudienceDraftRefs(audienceRefs);
    setAudienceModalOpen(true);
    await loadAudienceOptions();
  };

  const confirmAudienceSelector = () => {
    if (audienceDraftRefs.length === 0) {
      message.warning(t('itsm.catalog.audienceRequired'));
      return;
    }
    setAudienceRefs(audienceDraftRefs);
    setAudienceModalOpen(false);
  };

  const selectCatalog = (catalogId: string | null) => {
    if (catalogId === selectedCatalog) return;
    const nextHistory = catalogHistory.slice(0, catalogHistoryIndex + 1);
    nextHistory.push(catalogId);
    setCatalogHistory(nextHistory);
    setCatalogHistoryIndex(nextHistory.length - 1);
    setSelectedCatalog(catalogId);
  };

  const goCatalogBack = () => {
    if (catalogHistoryIndex === 0) return;
    const nextIndex = catalogHistoryIndex - 1;
    setCatalogHistoryIndex(nextIndex);
    setSelectedCatalog(catalogHistory[nextIndex]);
  };

  const goCatalogForward = () => {
    if (catalogHistoryIndex >= catalogHistory.length - 1) return;
    const nextIndex = catalogHistoryIndex + 1;
    setCatalogHistoryIndex(nextIndex);
    setSelectedCatalog(catalogHistory[nextIndex]);
  };

  const setCatalogStatus = async (catalog: Catalog, status: Catalog['status']) => {
    if (catalog.status === status) return;
    try {
      await api.patch(`/catalogs/${catalog.id}`, { status });
      message.success(status === '上架' ? '服务目录已上架' : '服务目录已下架');
      void loadCatalogs();
    } catch {
      // 已统一提示
    }
  };

  const updateItemStatus = async (item: ServiceItem, status: ServiceItem['status']) => {
    if (item.status === status) return;
    try {
      await api.patch(`/service-items/${item.id}`, { status });
      message.success(status === '上架' ? '服务项已上架' : '服务项已下架');
      void loadItems();
      void loadCatalogs();
    } catch {
      // 已统一提示
    }
  };

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
    setAudienceMode('all');
    setAudienceRefs([]);
    setAudienceDraftRefs([]);
    itemForm.resetFields();
    itemForm.setFieldsValue({
      ...(selectedCatalog != null ? { catalog_id: selectedCatalog } : {}),
      target_audience_mode: 'all',
    });
    setItemModalOpen(true);
  };

  const openItemEdit = (it: ServiceItem) => {
    setEditingItem(it);
    const legacyCustom = it.target_audience_mode !== 'custom'
      && !!it.target_audience
      && it.target_audience !== '全体员工';
    const mode: 'all' | 'custom' = it.target_audience_mode === 'custom' || legacyCustom ? 'custom' : 'all';
    const refs = (it.target_audience_refs ?? []) as AudienceRef[];
    setAudienceMode(mode);
    setAudienceRefs(refs);
    setAudienceDraftRefs(refs);
    itemForm.setFieldsValue({
      name: it.name,
      catalog_id: it.catalog_id,
      service_type: it.service_type ?? undefined,
      owner: it.owner ?? undefined,
      description: it.description ?? undefined,
      sla_response_hours: it.sla_response_hours ?? undefined,
      sla_resolution_hours: it.sla_resolution_hours ?? undefined,
      target_audience_mode: mode,
      status: it.status,
    });
    setItemModalOpen(true);
  };

  const saveItem = async () => {
    const values = await itemForm.validateFields();
    if (audienceMode === 'custom' && audienceRefs.length === 0) {
      message.warning(t('itsm.catalog.audienceRequired'));
      return;
    }
    const payload = {
      ...values,
      target_audience_mode: audienceMode,
      target_audience_refs: audienceMode === 'custom' ? audienceRefs : [],
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
              record.is_example && !isAdmin ? null : (
                <Space size={8}>
                  {canManage && (
                    <>
                      <Tooltip title="上架">
                        <Button
                          type="link"
                          size="small"
                          aria-label={`上架服务项 ${record.name}`}
                          disabled={record.status === '上架' || record.is_example}
                          icon={<ArrowUpOutlined />}
                          style={{ padding: 0 }}
                          onClick={() => void updateItemStatus(record, '上架')}
                        />
                      </Tooltip>
                      <Tooltip title="下架">
                        <Button
                          type="link"
                          size="small"
                          aria-label={`下架服务项 ${record.name}`}
                          disabled={record.status === '下架' || record.is_example}
                          icon={<ArrowDownOutlined />}
                          style={{ padding: 0 }}
                          onClick={() => void updateItemStatus(record, '下架')}
                        />
                      </Tooltip>
                    </>
                  )}
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

  if (requesterPortal) {
    const visibleItems = items.filter((item) => item.status === '上架');
    return (
      <div className="service-portal">
        <section className="service-portal__hero">
          <div>
            <Typography.Title level={1}>你好，今天需要什么帮助？</Typography.Title>
            <Typography.Paragraph>搜索服务与知识，或从常用入口快速开始。</Typography.Paragraph>
            <Input
              size="large"
              allowClear
              prefix={<SearchOutlined />}
              placeholder="例如：VPN 无法连接、申请软件权限……"
              defaultValue={q}
              onPressEnter={(event) => setQ(event.currentTarget.value)}
            />
          </div>
          <div className="service-portal__actions">
            <button onClick={() => navigate('/itsm/tickets')}><CustomerServiceOutlined /><strong>提交工单</strong><span>故障与服务请求</span></button>
            <button onClick={() => navigate('/itsm/tickets')}><KeyOutlined /><strong>申请权限</strong><span>账号与系统权限</span></button>
            <button onClick={() => navigate('/itsm/knowledge')}><ReadOutlined /><strong>查询知识</strong><span>自助解决问题</span></button>
          </div>
        </section>
        <section className="service-portal__section">
          <div className="service-portal__heading">
            <div><span>服务目录</span><Typography.Title level={2}>选择你需要的服务</Typography.Title></div>
            <Input.Search allowClear placeholder="筛选服务" onSearch={setQ} />
          </div>
          <div className="service-portal__catalogs">
              <button className={selectedCatalog === null ? 'is-active' : ''} onClick={() => selectCatalog(null)}>
              <strong>全部服务</strong><span>{items.length} 个可用服务</span>
            </button>
            {catalogs.filter((c) => c.status === '上架').map((catalog) => (
              <button key={catalog.id} className={selectedCatalog === catalog.id ? 'is-active' : ''} onClick={() => selectCatalog(catalog.id)}>
                <strong>{catalog.name}</strong><span>{catalog.item_count} 个服务</span>
              </button>
            ))}
          </div>
          <div className="service-portal__items">
            {visibleItems.map((item) => (
              <article key={item.id}>
                <div className="service-portal__item-icon"><CustomerServiceOutlined /></div>
                <div><strong>{item.name}</strong><p>{item.description || item.service_type || '标准 IT 服务'}</p><span>{item.owner_name || 'IT 服务台'} · SLA {item.sla_response_hours ?? '-'}h</span></div>
                <Button type="text" shape="circle" icon={<RightOutlined />} />
              </article>
            ))}
            {!itemLoading && visibleItems.length === 0 && <Empty description="没有匹配的服务" />}
          </div>
        </section>
      </div>
    );
  }

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
              onClick={() => selectCatalog(null)}
              style={selectedCatalog === null ? { borderColor: '#1677ff' } : undefined}
            >
              <Typography.Text strong>{t('itsm.catalog.allItems')}</Typography.Text>
            </Card>
            {catalogs.map((c) => (
              <Card
                key={c.id}
                size="small"
                hoverable
                onClick={() => selectCatalog(c.id)}
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
                      {' · '}
                      <Typography.Text type="secondary">
                        上架中 {c.published_item_count ?? 0} · 已下架 {c.unpublished_item_count ?? 0}
                      </Typography.Text>
                    </Typography.Text>
                  </Space>
                  <Space size={0}>
                    {canManage && !c.is_example && (
                      <>
                        <Tooltip title="上架">
                          <Button
                            type="text"
                            size="small"
                            aria-label={`上架服务目录 ${c.name}`}
                            disabled={c.status === '上架'}
                            icon={<ArrowUpOutlined />}
                            onClick={(e) => {
                              e.stopPropagation();
                              void setCatalogStatus(c, '上架');
                            }}
                          />
                        </Tooltip>
                        <Tooltip title="下架">
                          <Button
                            type="text"
                            size="small"
                            aria-label={`下架服务目录 ${c.name}`}
                            disabled={c.status === '下架'}
                            icon={<ArrowDownOutlined />}
                            onClick={(e) => {
                              e.stopPropagation();
                              void setCatalogStatus(c, '下架');
                            }}
                          />
                        </Tooltip>
                      </>
                    )}
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
                    {canDelete && (!c.is_example || isAdmin) && (
                      <Popconfirm
                        title={t('common.deleteConfirm')}
                        description={
                          c.item_count > 0
                            ? t('itsm.catalog.deleteCatalogWithItems', { n: c.item_count })
                            : t('itsm.catalog.deleteCatalogDescription')
                        }
                        onConfirm={async () => {
                          await api.delete(`/catalogs/${c.id}?cascade=true`);
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
          title={
            <Space size={8}>
              <Typography.Text strong>{t('itsm.catalog.itemsTitle')}</Typography.Text>
              <Tooltip title="返回上一个服务目录">
                <Button
                  type="text"
                  size="small"
                  aria-label="返回上一个服务目录"
                  icon={<ArrowLeftOutlined />}
                  disabled={catalogHistoryIndex === 0}
                  onClick={goCatalogBack}
                />
              </Tooltip>
              <Tooltip title="前进到下一个服务目录">
                <Button
                  type="text"
                  size="small"
                  aria-label="前进到下一个服务目录"
                  icon={<ArrowRightOutlined />}
                  disabled={catalogHistoryIndex >= catalogHistory.length - 1}
                  onClick={goCatalogForward}
                />
              </Tooltip>
            </Space>
          }
          extra={
            <Space>
              <Input.Search
                placeholder={t('itsm.catalog.searchItem')}
                allowClear
                style={{ width: 200 }}
                value={q}
                onChange={(event) => setQ(event.target.value)}
                onSearch={setQ}
              />
              <Select
                placeholder="筛选状态"
                prefix={<FilterOutlined />}
                style={{ width: 132 }}
                value={itemStatus}
                onChange={(value) => setItemStatus((value as '全部' | '上架' | '下架') || '全部')}
                options={[
                  { value: '全部', label: '全部' },
                  { value: '上架', label: '上架中' },
                  { value: '下架', label: '已下架' },
                ]}
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
          <SortableTable<ServiceItem>
            rowKey="id"
            loading={itemLoading}
            columns={columns}
            dataSource={items}
            sticky
            scroll={{ x: 'max-content' }}
            pagination={{
              current: itemPage,
              pageSize: itemPageSize,
              showSizeChanger: true,
              pageSizeOptions: [10, 20, 50, 100],
              showTotal: (n) => t('itsm.total', { n }),
              onChange: (page, pageSize) => {
                setItemPage(page);
                setItemPageSize(pageSize);
              },
            }}
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
          <Form.Item
            name="target_audience_mode"
            label={t('itsm.f.targetAudience')}
            rules={[{ required: true, message: t('itsm.catalog.audienceModeRequired') }]}
          >
            <Select
              options={[
                { value: 'all', label: t('itsm.catalog.allEmployees') },
                { value: 'custom', label: t('itsm.catalog.customAudience') },
              ]}
              onChange={(value: 'all' | 'custom') => {
                setAudienceMode(value);
                if (value === 'all') {
                  setAudienceRefs([]);
                  setAudienceDraftRefs([]);
                }
              }}
            />
          </Form.Item>
          {audienceMode === 'custom' ? (
            <Form.Item label={t('itsm.catalog.selectAudience')}>
              <Button block onClick={() => void openAudienceSelector()}>
                {audienceSummary}
              </Button>
              <Typography.Text type="secondary">{t('itsm.catalog.audienceCustomHint')}</Typography.Text>
              {editingItem
                && editingItem.target_audience_mode !== 'custom'
                && editingItem.target_audience
                && editingItem.target_audience !== '全体员工'
                && audienceRefs.length === 0 && (
                  <Alert
                    type="warning"
                    showIcon
                    style={{ marginTop: 8 }}
                    message={t('itsm.catalog.legacyAudienceHint')}
                  />
                )}
            </Form.Item>
          ) : (
            <Form.Item label={t('itsm.catalog.audienceSummary')}>
              <Typography.Text>{t('itsm.catalog.allEmployees')}</Typography.Text>
            </Form.Item>
          )}
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

      <Modal
        title={t('itsm.catalog.audienceTreeTitle')}
        open={audienceModalOpen}
        onOk={confirmAudienceSelector}
        confirmLoading={audienceLoading}
        onCancel={() => setAudienceModalOpen(false)}
        destroyOnClose
        width={640}
      >
        <Alert
          type="info"
          showIcon
          message={t('itsm.catalog.audienceTreeHint')}
          style={{ marginBottom: 12 }}
        />
        <Tree
          checkable
          checkStrictly
          defaultExpandAll
          treeData={audienceTreeData}
          checkedKeys={audienceDraftRefs.map((ref) => `audience-${ref.type}:${ref.id}`)}
          onCheck={(checkedKeys) => {
            const keys = Array.isArray(checkedKeys) ? checkedKeys : checkedKeys.checked;
            setAudienceDraftRefs(parseAudienceKeys(keys));
          }}
        />
      </Modal>
    </Row>
  );
}
