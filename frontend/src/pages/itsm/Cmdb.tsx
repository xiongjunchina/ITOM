import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Button,
  Card,
  DatePicker,
  Descriptions,
  Divider,
  Drawer,
  Form,
  Input,
  List,
  Popconfirm,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  ApartmentOutlined,
  ArrowDownOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  MinusCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { api } from '../../api/client';
import { ExampleTag } from '../../components/ExampleTag';
import ImportButtons from '../../components/ImportButtons';
import { hasAnyRole, useAuthStore } from '../../stores/auth';
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';
import type {
  CiImpact,
  CiRelationEntry,
  CiRow,
  MasterDataItem,
  Member,
  TicketPriority,
  Vendor,
} from '../../api/types';
import {
  CI_ENV_OPTIONS,
  CI_RELATION_TYPES,
  CI_STATUS_COLORS,
  CI_STATUS_OPTIONS,
  PRIORITY_COLORS,
} from '../../api/types';

interface CiFormValues {
  name: string;
  category: string;
  owner: string;
  status: string;
  environment?: string;
  business_owner?: string;
  vendor_id?: string;
  description?: string;
  launch_date?: Dayjs;
  attrs?: { key: string; value: string }[];
  remarks?: string;
}

/** CI 写操作角色 */
const CI_WRITERS = ['it_ops', 'is_mgr', 'cio', 'admin'] as const;

export default function Cmdb() {
  const user = useAuthStore((s) => s.user);
  const canWrite = hasAnyRole(user, [...CI_WRITERS]);
  const t = useT();
  const et = useEnums();

  const [items, setItems] = useState<CiRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);

  // 类别 Tabs + 筛选
  const [categories, setCategories] = useState<MasterDataItem[]>([]);
  const [category, setCategory] = useState('');
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<string | undefined>();
  const [environment, setEnvironment] = useState<string | undefined>();

  // 新建/编辑 Drawer
  const [editOpen, setEditOpen] = useState(false);
  const [editing, setEditing] = useState<CiRow | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<CiFormValues>();
  const [members, setMembers] = useState<Member[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);

  // 影响分析 Drawer
  const [impactCi, setImpactCi] = useState<CiRow | null>(null);
  const [impact, setImpact] = useState<CiImpact | null>(null);
  const [impactLoading, setImpactLoading] = useState(false);
  // 添加关系
  const [relForm] = Form.useForm<{ direction: 'upstream' | 'downstream'; relation_type: string; other_ci_id: string }>();
  const [relSaving, setRelSaving] = useState(false);
  const [ciOptions, setCiOptions] = useState<CiRow[]>([]);
  const [ciSearching, setCiSearching] = useState(false);

  const categoryName = (code: string) => categories.find((c) => c.code === code)?.name ?? code;

  useEffect(() => {
    api
      .getList<MasterDataItem>('/admin/master-data', { category: 'ci_category', page: 1, page_size: 999 })
      .then((res) => setCategories(res.items.filter((c) => c.active !== false)))
      .catch(() => undefined);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<CiRow>('/cis', {
        page,
        page_size: pageSize,
        q: q || undefined,
        category: category || undefined,
        status: status || undefined,
        environment: environment || undefined,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, q, category, status, environment]);

  useEffect(() => {
    void load();
  }, [load]);

  const ensureRefData = () => {
    if (members.length === 0) {
      api
        .getList<Member>('/members', { page: 1, page_size: 999 })
        .then((res) => setMembers(res.items))
        .catch(() => undefined);
    }
    if (vendors.length === 0) {
      api
        .getList<Vendor>('/vendors', { page: 1, page_size: 999 })
        .then((res) => setVendors(res.items))
        .catch(() => undefined);
    }
  };

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ status: '运行中', category: category || undefined });
    ensureRefData();
    setEditOpen(true);
  };

  const openEdit = (row: CiRow) => {
    setEditing(row);
    form.resetFields();
    form.setFieldsValue({
      name: row.name,
      category: row.category,
      owner: row.owner ?? undefined,
      status: row.status,
      environment: row.environment ?? undefined,
      business_owner: row.business_owner ?? undefined,
      vendor_id: row.vendor_id ?? undefined,
      description: row.description ?? undefined,
      launch_date: row.launch_date ? dayjs(row.launch_date) : undefined,
      attrs: Object.entries(row.attrs ?? {}).map(([key, value]) => ({ key, value: String(value ?? '') })),
      remarks: row.remarks ?? undefined,
    });
    ensureRefData();
    setEditOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    const attrs: Record<string, string> = {};
    (values.attrs ?? []).forEach((kv) => {
      if (kv?.key) attrs[kv.key] = kv.value ?? '';
    });
    const payload: Record<string, unknown> = {
      name: values.name,
      category: values.category,
      owner: values.owner,
      status: values.status,
      environment: values.environment ?? null,
      business_owner: values.business_owner ?? null,
      vendor_id: values.vendor_id ?? null,
      description: values.description ?? null,
      launch_date: values.launch_date ? values.launch_date.format('YYYY-MM-DD') : null,
      attrs,
      remarks: values.remarks ?? null,
    };
    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/cis/${editing.id}`, payload);
        message.success(t('itsm.cmdb.updated'));
      } else {
        await api.post('/cis', payload);
        message.success(t('itsm.cmdb.created'));
      }
      setEditOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const loadImpact = useCallback(async (ci: CiRow) => {
    setImpactLoading(true);
    try {
      const data = await api.get<CiImpact>(`/cis/${ci.id}/impact`);
      setImpact(data);
    } catch {
      // 已统一提示
    } finally {
      setImpactLoading(false);
    }
  }, []);

  const openImpact = (row: CiRow) => {
    setImpactCi(row);
    setImpact(null);
    relForm.resetFields();
    void loadImpact(row);
  };

  const searchCis = (kw: string) => {
    setCiSearching(true);
    api
      .getList<CiRow>('/cis', { page: 1, page_size: 20, q: kw || undefined })
      .then((res) => setCiOptions(res.items.filter((c) => c.id !== impactCi?.id)))
      .catch(() => undefined)
      .finally(() => setCiSearching(false));
  };

  const submitRelation = async () => {
    if (!impactCi) return;
    const values = await relForm.validateFields();
    // upstream = 本 CI 作为源（本 CI 运行于/依赖/连接 目标）；downstream = 对方作为源
    const source_ci_id = values.direction === 'upstream' ? impactCi.id : values.other_ci_id;
    const target_ci_id = values.direction === 'upstream' ? values.other_ci_id : impactCi.id;
    setRelSaving(true);
    try {
      await api.post('/ci-relationships', {
        source_ci_id,
        target_ci_id,
        relation_type: values.relation_type,
      });
      message.success(t('itsm.cmdb.relAdded'));
      relForm.resetFields();
      void loadImpact(impactCi);
    } catch {
      // 已统一提示
    } finally {
      setRelSaving(false);
    }
  };

  const deleteRelation = async (relationId: string) => {
    if (!impactCi) return;
    try {
      await api.delete(`/ci-relationships/${relationId}`);
      message.success(t('itsm.cmdb.relDeleted'));
      void loadImpact(impactCi);
    } catch {
      // 已统一提示
    }
  };

  const columns: ColumnsType<CiRow> = [
    {
      title: t('itsm.f.code'),
      dataIndex: 'ci_code',
      width: 140,
      fixed: 'left',
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (v: string, r) => <a onClick={() => openImpact(r)}>{v}</a>,
    },
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
    { title: t('itsm.f.category'), dataIndex: 'category', width: 120, render: (v: string) => categoryName(v) },
    { title: t('itsm.f.env'), dataIndex: 'environment', width: 80, render: (v) => (v ? et.ciEnv(v) : '-') },
    {
      title: t('common.status'),
      dataIndex: 'status',
      width: 90,
      render: (v: string) => <Tag color={CI_STATUS_COLORS[v] ?? 'default'}>{et.ciStatus(v)}</Tag>,
    },
    { title: t('itsm.f.owner'), dataIndex: 'owner_name', width: 100, render: (v) => v || '-' },
    { title: t('itsm.f.vendor'), dataIndex: 'vendor_name', width: 140, ellipsis: true, render: (v) => v || '-' },
    {
      title: t('common.actions'),
      key: 'actions',
      width: 150,
      render: (_, r) => (
        <Space size={0}>
          <Button type="link" size="small" icon={<ApartmentOutlined />} onClick={() => openImpact(r)}>
            {t('itsm.cmdb.impact')}
          </Button>
          {canWrite && !r.is_example && (
            <Button type="link" size="small" onClick={() => openEdit(r)}>
              {t('common.edit')}
            </Button>
          )}
        </Space>
      ),
    },
  ];

  const relationList = (title: string, icon: JSX.Element, entries: CiRelationEntry[], hint: string) => (
    <>
      <Typography.Text strong>
        {icon} {title}
      </Typography.Text>
      <List<CiRelationEntry>
        size="small"
        dataSource={entries}
        locale={{ emptyText: hint }}
        renderItem={(e) => (
          <List.Item
            actions={
              canWrite && !impactCi?.is_example
                ? [
                    <Popconfirm
                      key="del"
                      title={t('itsm.cmdb.delRelConfirm')}
                      onConfirm={() => void deleteRelation(e.relation_id)}
                    >
                      <Button type="text" size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>,
                  ]
                : undefined
            }
          >
            <Space>
              <Tag>{et.ciRelation(e.relation_type)}</Tag>
              <span>{e.ci.name}</span>
              <Typography.Text type="secondary">
                {e.ci.category ? categoryName(e.ci.category) : ''}
                {e.ci.status ? ` · ${et.ciStatus(e.ci.status)}` : ''}
              </Typography.Text>
            </Space>
          </List.Item>
        )}
      />
    </>
  );

  const impactTicketColumns: ColumnsType<CiImpact['tickets'][number]> = [
    {
      title: t('itsm.f.code'),
      dataIndex: 'ticket_code',
      width: 140,
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (v: string, r) => <Link to={`/itsm/tickets/${r.id}`}>{v}</Link>,
    },
    { title: t('itsm.f.title'), dataIndex: 'title', ellipsis: true },
    {
      title: t('itsm.f.priority'),
      dataIndex: 'priority',
      width: 80,
      render: (v: TicketPriority) => <Tag color={PRIORITY_COLORS[v]}>{v}</Tag>,
    },
    { title: t('common.status'), dataIndex: 'status', width: 100 },
    {
      title: t('itsm.f.submittedAt'),
      dataIndex: 'submitted_at',
      width: 140,
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'),
    },
  ];

  return (
    <Card
      title={t('itsm.cmdb.title')}
      extra={
        canWrite && (
          <Space>
            <ImportButtons
              templateUrl="/itsm-import/ci/template"
              importUrl="/itsm-import/ci"
              onDone={() => void load()}
            />
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              {t('itsm.cmdb.newCi')}
            </Button>
          </Space>
        )
      }
    >
      <Tabs
        activeKey={category}
        onChange={(k) => {
          setPage(1);
          setCategory(k);
        }}
        items={[
          { key: '', label: t('common.all') },
          ...categories.map((c) => ({ key: c.code, label: c.name })),
        ]}
      />

      <Space wrap style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder={t('itsm.cmdb.searchPlaceholder')}
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
          style={{ width: 110 }}
          value={status}
          onChange={(v) => {
            setPage(1);
            setStatus(v);
          }}
          options={CI_STATUS_OPTIONS.map((s) => ({ value: s, label: et.ciStatus(s) }))}
        />
        <Select
          placeholder={t('itsm.f.env')}
          allowClear
          style={{ width: 110 }}
          value={environment}
          onChange={(v) => {
            setPage(1);
            setEnvironment(v);
          }}
          options={CI_ENV_OPTIONS.map((s) => ({ value: s, label: et.ciEnv(s) }))}
        />
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>
          {t('common.refresh')}
        </Button>
      </Space>

      <Table<CiRow>
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

      {/* 新建/编辑 Drawer */}
      <Drawer
        title={editing ? t('itsm.cmdb.editCi', { code: editing.ci_code }) : t('itsm.cmdb.newCi')}
        open={editOpen}
        width={560}
        onClose={() => setEditOpen(false)}
        destroyOnClose
        extra={
          <Space>
            <Button onClick={() => setEditOpen(false)}>{t('common.cancel')}</Button>
            <Button type="primary" loading={saving} onClick={() => void handleSave()}>
              {t('common.save')}
            </Button>
          </Space>
        }
      >
        <Form<CiFormValues> form={form} layout="vertical" preserve={false}>
          <Form.Item name="name" label={t('itsm.f.name')} rules={[{ required: true, message: t('itsm.rule.name') }]}>
            <Input maxLength={128} placeholder={t('itsm.cmdb.namePlaceholder')} />
          </Form.Item>
          <Form.Item name="category" label={t('itsm.f.category')} rules={[{ required: true, message: t('itsm.cmdb.categoryRequired') }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder={t('itsm.cmdb.categoryPlaceholder')}
              options={categories.map((c) => ({ value: c.code, label: c.name }))}
            />
          </Form.Item>
          <Form.Item name="owner" label={t('itsm.f.owner')} rules={[{ required: true, message: t('itsm.rule.owner') }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder={t('itsm.ownerPlaceholder')}
              options={members.map((m) => ({
                value: m.id,
                label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
              }))}
            />
          </Form.Item>
          <Form.Item name="status" label={t('common.status')} rules={[{ required: true }]}>
            <Select options={CI_STATUS_OPTIONS.map((s) => ({ value: s, label: et.ciStatus(s) }))} />
          </Form.Item>
          <Form.Item name="environment" label={t('itsm.f.env')}>
            <Select allowClear options={CI_ENV_OPTIONS.map((s) => ({ value: s, label: et.ciEnv(s) }))} />
          </Form.Item>
          <Form.Item name="business_owner" label={t('itsm.cmdb.businessOwner')}>
            <Input maxLength={64} placeholder={t('itsm.cmdb.businessOwnerPlaceholder')} />
          </Form.Item>
          <Form.Item name="vendor_id" label={t('itsm.f.vendor')}>
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder={t('itsm.selectVendor')}
              options={vendors.map((v) => ({ value: v.id, label: v.name }))}
            />
          </Form.Item>
          <Form.Item name="launch_date" label={t('itsm.f.launchDate')}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="description" label={t('itsm.f.description')}>
            <Input.TextArea rows={3} maxLength={2000} />
          </Form.Item>

          <Form.Item label={t('itsm.cmdb.attrs')}>
            <Form.List name="attrs">
              {(fields, { add, remove }) => (
                <>
                  {fields.map(({ key, name, ...rest }) => (
                    <Space key={key} align="baseline" style={{ display: 'flex', marginBottom: 8 }}>
                      <Form.Item
                        {...rest}
                        name={[name, 'key']}
                        rules={[{ required: true, message: t('itsm.cmdb.attrKeyRequired') }]}
                        style={{ marginBottom: 0 }}
                      >
                        <Input placeholder={t('itsm.cmdb.attrKeyPlaceholder')} style={{ width: 160 }} />
                      </Form.Item>
                      <Form.Item {...rest} name={[name, 'value']} style={{ marginBottom: 0 }}>
                        <Input placeholder={t('itsm.cmdb.attrValuePlaceholder')} style={{ width: 240 }} />
                      </Form.Item>
                      <MinusCircleOutlined onClick={() => remove(name)} />
                    </Space>
                  ))}
                  <Button type="dashed" block icon={<PlusOutlined />} onClick={() => add({ key: '', value: '' })}>
                    {t('itsm.cmdb.addAttr')}
                  </Button>
                </>
              )}
            </Form.List>
          </Form.Item>

          <Form.Item name="remarks" label={t('common.remark')}>
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Drawer>

      {/* 影响分析 Drawer */}
      <Drawer
        title={impactCi ? t('itsm.cmdb.impactTitle', { code: impactCi.ci_code, name: impactCi.name }) : t('itsm.cmdb.impact')}
        open={!!impactCi}
        width={680}
        onClose={() => setImpactCi(null)}
        destroyOnClose
      >
        {impactLoading || !impact ? (
          <div style={{ textAlign: 'center', padding: 60 }}>
            <Spin />
          </div>
        ) : (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label={t('itsm.f.category')}>{categoryName(impact.ci.category)}</Descriptions.Item>
              <Descriptions.Item label={t('common.status')}>
                <Tag color={CI_STATUS_COLORS[impact.ci.status] ?? 'default'}>{et.ciStatus(impact.ci.status)}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label={t('itsm.f.env')}>{impact.ci.environment ? et.ciEnv(impact.ci.environment) : '-'}</Descriptions.Item>
              <Descriptions.Item label={t('itsm.f.owner')}>{impact.ci.owner_name ?? '-'}</Descriptions.Item>
              {Object.entries(impact.ci.attrs ?? {}).map(([k, v]) => (
                <Descriptions.Item key={k} label={k}>
                  {String(v ?? '-')}
                </Descriptions.Item>
              ))}
            </Descriptions>

            {relationList(
              t('itsm.cmdb.upstream'),
              <ArrowUpOutlined />,
              impact.upstream,
              t('itsm.cmdb.noUpstream'),
            )}
            {relationList(
              t('itsm.cmdb.downstream'),
              <ArrowDownOutlined />,
              impact.downstream,
              t('itsm.cmdb.noDownstream'),
            )}

            {canWrite && !impactCi?.is_example && (
              <>
                <Divider style={{ margin: '8px 0' }} />
                <Typography.Text strong>{t('itsm.cmdb.addRel')}</Typography.Text>
                <Form
                  form={relForm}
                  layout="inline"
                  initialValues={{ direction: 'upstream', relation_type: '依赖' }}
                >
                  <Form.Item name="direction" rules={[{ required: true }]}>
                    <Select
                      style={{ width: 150 }}
                      options={[
                        { value: 'upstream', label: t('itsm.cmdb.dirUpstream') },
                        { value: 'downstream', label: t('itsm.cmdb.dirDownstream') },
                      ]}
                    />
                  </Form.Item>
                  <Form.Item name="relation_type" rules={[{ required: true, message: t('itsm.cmdb.relTypeRequired') }]}>
                    <Select
                      style={{ width: 110 }}
                      options={CI_RELATION_TYPES.map((rt) => ({ value: rt, label: et.ciRelation(rt) }))}
                    />
                  </Form.Item>
                  <Form.Item name="other_ci_id" rules={[{ required: true, message: t('itsm.cmdb.targetCiRequired') }]}>
                    <Select
                      style={{ width: 200 }}
                      showSearch
                      filterOption={false}
                      loading={ciSearching}
                      placeholder={t('itsm.cmdb.searchTargetCi')}
                      onSearch={searchCis}
                      onFocus={() => searchCis('')}
                      notFoundContent={ciSearching ? <Spin size="small" /> : t('itsm.cmdb.noMatchCi')}
                      options={ciOptions.map((c) => ({ value: c.id, label: `${c.ci_code} ${c.name}` }))}
                    />
                  </Form.Item>
                  <Form.Item>
                    <Button type="primary" loading={relSaving} onClick={() => void submitRelation()}>
                      {t('itsm.add')}
                    </Button>
                  </Form.Item>
                </Form>
              </>
            )}

            <Divider style={{ margin: '8px 0' }} />
            <Typography.Text strong>{t('itsm.cmdb.linkedTickets')}</Typography.Text>
            <Table<CiImpact['tickets'][number]>
              rowKey="id"
              size="small"
              columns={impactTicketColumns}
              dataSource={impact.tickets}
              pagination={false}
              locale={{ emptyText: t('itsm.noLinkedTickets') }}
            />
          </Space>
        )}
      </Drawer>
    </Card>
  );
}
