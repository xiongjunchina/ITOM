import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Progress,
  Segmented,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { AppstoreOutlined, PlusOutlined, ReloadOutlined, TableOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import { useAuthStore, hasPermission } from '../../stores/auth';
import type {
  BusinessDomain,
  MasterDataItem,
  Moscow,
  RequirementRow,
  RequirementStatus,
} from '../../api/types';
import { MOSCOW_KEYS, MOSCOW_META, REQ_STATUS, REQ_TYPES } from '../../api/types';
import { MoscowTag, ReqStatusBadge } from './shared';

const STATUS_OPTIONS = (Object.keys(REQ_STATUS) as RequirementStatus[]).map((s) => ({
  value: s,
  label: REQ_STATUS[s].label,
}));

const MOSCOW_OPTIONS = MOSCOW_KEYS.map((k) => ({ value: k, label: MOSCOW_META[k].label }));

/** 看板四列：on_hold / cancelled 不入看板（表格视图可见） */
const BOARD_COLS: RequirementStatus[] = ['registered', 'analyzing', 'implementing', 'closed'];

/** 写权限：优先权限矩阵；存量会话缺失 permissions 时放行（后端仍会校验并中文提示） */
function useReqPerm(action: 'create' | 'edit'): boolean {
  const user = useAuthStore((s) => s.user);
  return user?.permissions ? hasPermission(user, 'requirements', action) : true;
}

interface CreateFormValues {
  title: string;
  req_type: string;
  business_domain_id: string;
  description: string;
  source?: string;
}

// ---------------- 看板卡片 ----------------

function BoardCard({ row, onClick }: { row: RequirementRow; onClick: () => void }) {
  return (
    <Card
      size="small"
      hoverable
      onClick={onClick}
      styles={{ body: { padding: '8px 12px' } }}
      style={{ marginBottom: 8 }}
    >
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {row.requirement_code}
      </Typography.Text>
      <Typography.Paragraph strong ellipsis={{ rows: 2, tooltip: row.title }} style={{ margin: '2px 0 6px' }}>
        {row.title}
      </Typography.Paragraph>
      <Space size={4} wrap>
        <MoscowTag value={row.moscow} empty={null} />
        {row.business_domain_name && <Tag style={{ marginInlineEnd: 0 }}>{row.business_domain_name}</Tag>}
      </Space>
      <div
        style={{
          marginTop: 6,
          display: 'flex',
          justifyContent: 'space-between',
          fontSize: 12,
          color: 'rgba(0,0,0,0.45)',
        }}
      >
        <span>{row.owner_name || '未指派'}</span>
        {row.task_total > 0 && (
          <span>
            任务 {row.task_done}/{row.task_total}
          </span>
        )}
      </div>
      {row.task_total > 0 && (
        <Progress percent={row.progress ?? 0} size="small" showInfo={false} style={{ margin: '4px 0 0' }} />
      )}
    </Card>
  );
}

// ---------------- 页面 ----------------

export default function Requirements() {
  const navigate = useNavigate();
  const canCreate = useReqPerm('create');

  const [view, setView] = useState<'board' | 'table'>('board');
  const [items, setItems] = useState<RequirementRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);

  // 筛选
  const [q, setQ] = useState('');
  const [domainId, setDomainId] = useState<string | undefined>();
  const [moscow, setMoscow] = useState<Moscow | undefined>();
  const [status, setStatus] = useState<string | undefined>(); // 仅表格视图
  const [mineOnly, setMineOnly] = useState(false);
  const [domains, setDomains] = useState<BusinessDomain[]>([]);

  // 登记需求
  const [createOpen, setCreateOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<CreateFormValues>();
  const [sources, setSources] = useState<MasterDataItem[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const base = {
        q: q || undefined,
        business_domain_id: domainId || undefined,
        moscow: moscow || undefined,
        scope: mineOnly ? 'mine' : undefined,
      };
      // 看板：一次拉全量（上限 200 条，与后端分页上限一致），状态在前端分列
      const res =
        view === 'board'
          ? await api.getList<RequirementRow>('/requirements', { ...base, page: 1, page_size: 200 })
          : await api.getList<RequirementRow>('/requirements', {
              ...base,
              status: status || undefined,
              page,
              page_size: pageSize,
            });
      setItems(res.items);
      setTotal(res.total);
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, [view, q, domainId, moscow, status, mineOnly, page, pageSize]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    api
      .getList<BusinessDomain>('/admin/business-domains')
      .then((res) => setDomains(res.items.filter((d) => d.active)))
      .catch(() => undefined);
  }, []);

  const boardGroups = useMemo(() => {
    const groups = new Map<RequirementStatus, RequirementRow[]>(BOARD_COLS.map((s) => [s, []]));
    items.forEach((r) => {
      const col = groups.get(r.status as RequirementStatus);
      if (col) col.push(r);
    });
    return groups;
  }, [items]);

  const openCreate = () => {
    form.resetFields();
    setCreateOpen(true);
    if (sources.length === 0) {
      api
        .getList<MasterDataItem>('/admin/master-data', {
          category: 'requirement_source',
          page: 1,
          page_size: 999,
        })
        .then((res) => setSources(res.items.filter((s) => s.active !== false)))
        .catch(() => undefined);
    }
  };

  const submitCreate = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const created = await api.post<RequirementRow>('/requirements', {
        title: values.title,
        req_type: values.req_type,
        business_domain_id: values.business_domain_id,
        description: values.description,
        source: values.source ?? null,
      });
      message.success(`需求 ${created.requirement_code ?? ''} 已登记`);
      setCreateOpen(false);
      if (created?.id) {
        navigate(`/requirements/${created.id}`);
      } else {
        void load();
      }
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  // ----- 表格视图 -----
  const columns: ColumnsType<RequirementRow> = [
    {
      title: '编号',
      dataIndex: 'requirement_code',
      width: 110,
      fixed: 'left',
      render: (v: string, r) => <Link to={`/requirements/${r.id}`}>{v}</Link>,
    },
    { title: '标题', dataIndex: 'title', width: 240, ellipsis: true },
    { title: '类型', dataIndex: 'req_type', width: 80 },
    { title: '业务域', dataIndex: 'business_domain_name', width: 130, ellipsis: true, render: (v) => v || '-' },
    {
      title: 'MoSCoW',
      dataIndex: 'moscow',
      width: 100,
      render: (v: string | null) => <MoscowTag value={v} />,
    },
    { title: '负责人', dataIndex: 'owner_name', width: 100, render: (v) => v || '-' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (_, r) => <ReqStatusBadge status={r.status} name={r.status_name} />,
    },
    { title: '目标日期', dataIndex: 'target_date', width: 110, render: (v) => v || '-' },
    {
      title: '进度',
      dataIndex: 'progress',
      width: 140,
      render: (v: number | null, r) =>
        r.task_total === 0 ? (
          '-'
        ) : (
          <Progress percent={v ?? 0} size="small" format={() => `${r.task_done}/${r.task_total}`} />
        ),
    },
    {
      title: '交付周期',
      dataIndex: 'lead_days',
      width: 100,
      render: (v: number | null) => (v == null ? '-' : `${v} 天`),
    },
  ];

  // ----- 看板视图 -----
  const boardView = (
    <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', overflowX: 'auto' }}>
      {BOARD_COLS.map((s) => {
        const rows = boardGroups.get(s) ?? [];
        return (
          <div
            key={s}
            style={{
              flex: '1 1 0',
              minWidth: 240,
              background: '#f5f5f5',
              borderRadius: 8,
              padding: 8,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0 4px 8px' }}>
              <ReqStatusBadge status={s} />
              <Tag style={{ marginInlineEnd: 0 }}>{rows.length}</Tag>
            </div>
            {rows.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无需求" style={{ margin: '24px 0' }} />
            ) : (
              rows.map((r) => <BoardCard key={r.id} row={r} onClick={() => navigate(`/requirements/${r.id}`)} />)
            )}
          </div>
        );
      })}
    </div>
  );

  return (
    <Card title="需求管理">
      <Space wrap style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}>
        <Space wrap>
          <Segmented
            value={view}
            onChange={(v) => {
              setPage(1);
              setView(v as 'board' | 'table');
            }}
            options={[
              { value: 'board', label: '看板', icon: <AppstoreOutlined /> },
              { value: 'table', label: '表格', icon: <TableOutlined /> },
            ]}
          />
          <Input.Search
            placeholder="搜索编号/标题"
            allowClear
            style={{ width: 200 }}
            onSearch={(v) => {
              setPage(1);
              setQ(v);
            }}
          />
          <Select
            placeholder="业务域"
            allowClear
            showSearch
            optionFilterProp="label"
            style={{ width: 150 }}
            value={domainId}
            onChange={(v) => {
              setPage(1);
              setDomainId(v);
            }}
            options={domains.map((d) => ({ value: d.id, label: d.name }))}
          />
          <Select
            placeholder="MoSCoW"
            allowClear
            style={{ width: 120 }}
            value={moscow}
            onChange={(v) => {
              setPage(1);
              setMoscow(v);
            }}
            options={MOSCOW_OPTIONS}
          />
          {view === 'table' && (
            <Select
              placeholder="状态"
              allowClear
              style={{ width: 110 }}
              value={status}
              onChange={(v) => {
                setPage(1);
                setStatus(v);
              }}
              options={STATUS_OPTIONS}
            />
          )}
          <span>
            只看我的{' '}
            <Switch
              checked={mineOnly}
              onChange={(v) => {
                setPage(1);
                setMineOnly(v);
              }}
            />
          </span>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>
            刷新
          </Button>
        </Space>
        {canCreate && (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            登记需求
          </Button>
        )}
      </Space>

      {view === 'board' ? (
        <Spin spinning={loading}>
          {total > items.length && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message={`当前筛选共 ${total} 条需求，看板仅展示最近 ${items.length} 条，可切换表格视图查看全部`}
            />
          )}
          {boardView}
        </Spin>
      ) : (
        <Table<RequirementRow>
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={items}
          scroll={{ x: 1200 }}
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
      )}

      {/* 登记需求 Modal（极简 4+1 字段，30 秒完成） */}
      <Modal
        title="登记需求"
        open={createOpen}
        width={560}
        onOk={() => void submitCreate()}
        confirmLoading={saving}
        onCancel={() => setCreateOpen(false)}
        destroyOnClose
      >
        <Form<CreateFormValues> form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="title"
            label="需求标题"
            rules={[
              { required: true, message: '请输入需求标题' },
              { min: 2, message: '至少 2 个字符' },
            ]}
          >
            <Input maxLength={200} placeholder="一句话说清要什么" />
          </Form.Item>
          <Form.Item name="req_type" label="需求类型" rules={[{ required: true, message: '请选择需求类型' }]}>
            <Select placeholder="选择类型" options={REQ_TYPES.map((t) => ({ value: t, label: t }))} />
          </Form.Item>
          <Form.Item
            name="business_domain_id"
            label="所属业务域"
            rules={[{ required: true, message: '请选择所属业务域' }]}
          >
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="选择业务域"
              options={domains.map((d) => ({ value: d.id, label: d.name }))}
            />
          </Form.Item>
          <Form.Item name="description" label="需求描述" rules={[{ required: true, message: '请输入需求描述' }]}>
            <Input.TextArea rows={4} maxLength={2000} placeholder="背景、期望达成的效果" />
          </Form.Item>
          <Form.Item name="source" label="需求来源">
            <Select
              allowClear
              placeholder="选择来源（可选）"
              options={sources.map((s) => ({ value: s.name, label: s.name }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
