import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  Alert,
  Button,
  Card,
  Collapse,
  DatePicker,
  Empty,
  Form,
  Image,
  Input,
  Modal,
  Popconfirm,
  Progress,
  Segmented,
  Select,
  Space,
  Spin,
  Switch,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import Table from '../../components/SortableTable';
import {
  AppstoreOutlined,
  DownloadOutlined,
  ImportOutlined,
  PaperClipOutlined,
  PlusOutlined,
  ReloadOutlined,
  TableOutlined,
} from '@ant-design/icons';
import type { Dayjs } from 'dayjs';
import { api } from '../../api/client';
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';
import { ExampleTag } from '../../components/ExampleTag';
import PendingStepCell from '../../components/PendingStepCell';
import type { PendingStep } from '../../components/PendingStepCell';
import { useAuthStore, hasPermission } from '../../stores/auth';
import type {
  BusinessDomain,
  AttachmentItem,
  MasterDataItem,
  Moscow,
  RequirementRow,
  RequirementStatus,
} from '../../api/types';
import { MOSCOW_KEYS, REQ_DECISIONS, REQ_STATUS, REQ_TYPES } from '../../api/types';
import { DecisionTag, MoscowTag, QuadrantTag, ReqStatusBadge, RouteTag } from './shared';
import RequirementImportModal from './RequirementImportModal';
import DocumentTypeHint from '../../components/DocumentTypeHint';
import BatchDeleteToolbar from '../../components/BatchDeleteToolbar';

const STATUS_KEYS = Object.keys(REQ_STATUS) as RequirementStatus[];

/** 看板五列：登记→评估→分析→实现→关闭；on_hold / cancelled 不入看板（表格视图可见） */
const BOARD_COLS: RequirementStatus[] = ['registered', 'supplementing', 'evaluating', 'analyzing', 'implementing', 'closed'];

/** 加权总分展示：保留 1 位小数，空显示 - */
const fmtScore = (v?: number | null): string => (v == null ? '-' : v.toFixed(1));

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
  other_info?: string;
  source?: string;
  // 进阶字段（默认折叠）
  expected_date?: Dayjs;
  expected_effect?: string;
  business_value_note?: string;
}

type RequirementDraftAttachment = AttachmentItem & { previewUrl?: string };

const MAX_REQUIREMENT_ATTACHMENTS = 10;

// ---------------- 看板卡片 ----------------

function BoardCard({ row, onClick }: { row: RequirementRow; onClick: () => void }) {
  const t = useT();
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
        {row.is_example && <ExampleTag style={{ marginInlineEnd: 4 }} />}
        {row.title}
      </Typography.Paragraph>
      <Space size={4} wrap>
        <MoscowTag value={row.moscow} empty={null} />
        <QuadrantTag value={row.quadrant} empty={null} />
        <RouteTag value={row.route} empty={null} />
        {row.weighted_total != null && (
          <Tag color="blue" style={{ marginInlineEnd: 0 }}>
            {t('req.weightedTotal')} {fmtScore(row.weighted_total)}
          </Tag>
        )}
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
        <span>{row.owner_name || t('req.unassigned')}</span>
        {row.task_total > 0 && (
          <span>{t('req.tasksCount', { done: row.task_done, total: row.task_total })}</span>
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
  const t = useT();
  const et = useEnums();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const createRequested = searchParams.get('create') === '1';
  const canCreate = useReqPerm('create');
  const user = useAuthStore((s) => s.user);
  const canDelete = hasPermission(user, 'requirements', 'delete'); // M21：默认矩阵仅 admin
  const isAdmin = !!user?.permissions?.['*'];
  const MOSCOW_OPTIONS = MOSCOW_KEYS.map((k) => ({ value: k, label: et.moscow(k) }));

  const [view, setView] = useState<'board' | 'table'>('table');
  const [items, setItems] = useState<RequirementRow[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);

  // 筛选
  const [q, setQ] = useState('');
  const [domainId, setDomainId] = useState<string | undefined>();
  const [moscow, setMoscow] = useState<Moscow | undefined>();
  const [status, setStatus] = useState<string | undefined>(); // 仅表格视图
  const [decision, setDecision] = useState<string | undefined>(); // 仅表格视图
  const [mineOnly, setMineOnly] = useState(false);
  const [domains, setDomains] = useState<BusinessDomain[]>([]);

  // 登记需求 / 导入
  const [createOpen, setCreateOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<CreateFormValues>();
  const [sources, setSources] = useState<MasterDataItem[]>([]);
  const [importOpen, setImportOpen] = useState(false);
  const [draftAttachments, setDraftAttachments] = useState<RequirementDraftAttachment[]>([]);
  const [attachmentUploading, setAttachmentUploading] = useState(0);
  const directCreateStarted = useRef(false);

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
              decision: decision || undefined,
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
  }, [view, q, domainId, moscow, status, decision, mineOnly, page, pageSize]);

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
    draftAttachments.forEach((attachment) => {
      if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
    });
    form.resetFields();
    setDraftAttachments([]);
    setAttachmentUploading(0);
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

  // create=1 直达需求登记窗口；一次性 guard 避免 React StrictMode 重复打开。
  useEffect(() => {
    if (!createRequested || !canCreate || directCreateStarted.current) return;
    directCreateStarted.current = true;
    openCreate();
    // openCreate intentionally captures the current form/source loaders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [createRequested, canCreate]);

  const discardDraftAttachments = async (attachments = draftAttachments) => {
    attachments.forEach((attachment) => {
      if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
    });
    setDraftAttachments([]);
    await Promise.allSettled(attachments.map((attachment) => api.delete(`/attachments/requirement-drafts/${attachment.id}`)));
  };

  const closeCreate = () => {
    void discardDraftAttachments();
    setCreateOpen(false);
  };

  const stageRequirementAttachment = async (file: File) => {
    if (draftAttachments.length + attachmentUploading >= MAX_REQUIREMENT_ATTACHMENTS) {
      message.warning(t('req.attachmentLimit'));
      return;
    }
    const previewUrl = file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined;
    setAttachmentUploading((count) => count + 1);
    try {
      const uploaded = await api.upload<AttachmentItem>('/attachments/requirement-drafts', file);
      setDraftAttachments((items) => [...items, { ...uploaded, previewUrl }]);
    } catch {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      // 已统一提示
    } finally {
      setAttachmentUploading((count) => Math.max(0, count - 1));
    }
  };

  const removeDraftAttachment = async (attachment: RequirementDraftAttachment) => {
    try {
      await api.delete(`/attachments/requirement-drafts/${attachment.id}`);
      if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
      setDraftAttachments((items) => items.filter((item) => item.id !== attachment.id));
    } catch {
      // 已统一提示
    }
  };

  const submitCreate = async () => {
    if (attachmentUploading > 0) {
      message.warning(t('req.attachmentUploading'));
      return;
    }
    const values = await form.validateFields();
    setSaving(true);
    try {
      const created = await api.post<RequirementRow>('/requirements', {
        title: values.title,
        req_type: values.req_type,
        business_domain_id: values.business_domain_id,
        description: values.description,
        remarks: values.other_info || null,
        source: values.source ?? null,
        expected_date: values.expected_date ? values.expected_date.format('YYYY-MM-DD') : null,
        expected_effect: values.expected_effect || null,
        business_value_note: values.business_value_note || null,
        attachment_ids: draftAttachments.map((attachment) => attachment.id),
      });
      message.success(t('req.created', { code: created.requirement_code ?? '' }));
      setCreateOpen(false);
      draftAttachments.forEach((attachment) => {
        if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
      });
      setDraftAttachments([]);
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
      title: t('req.col.code'),
      dataIndex: 'requirement_code',
      width: 150,
      fixed: 'left',
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (v: string, r) => (
        <Space size={4}>
          <Link to={`/requirements/${r.id}`}>{v}</Link>
          {r.is_example && <ExampleTag />}
        </Space>
      ),
    },
    { title: t('req.col.title'), dataIndex: 'title', width: 280, ellipsis: true, fixed: 'left' },
    { title: t('req.requester'), dataIndex: 'requester_name', width: 110, render: (v) => v || '-' },
    { title: t('req.col.type'), dataIndex: 'req_type', width: 80, render: (v) => et.reqType(v) },
    { title: t('req.col.domain'), dataIndex: 'business_domain_name', width: 130, ellipsis: true, render: (v) => v || '-' },
    {
      title: 'MoSCoW',
      dataIndex: 'moscow',
      width: 100,
      render: (v: string | null) => <MoscowTag value={v} />,
    },
    {
      title: t('req.col.weightedTotal'),
      dataIndex: 'weighted_total',
      width: 100,
      align: 'right',
      render: (v: number | null) => fmtScore(v),
    },
    {
      title: t('req.col.quadrant'),
      dataIndex: 'quadrant',
      width: 120,
      render: (v: string | null) => <QuadrantTag value={v} />,
    },
    {
      title: t('req.col.decision'),
      dataIndex: 'decision',
      width: 90,
      render: (v: string | null) => <DecisionTag value={v} />,
    },
    {
      title: t('req.col.route'),
      dataIndex: 'route',
      width: 110,
      render: (v: string | null) => <RouteTag value={v} />,
    },
    { title: t('req.col.owner'), dataIndex: 'owner_name', width: 100, render: (v) => v || '-' },
    {
      title: t('common.status'),
      dataIndex: 'status',
      width: 100,
      render: (_, r) => <ReqStatusBadge status={r.status} name={r.status_name} />,
    },
    { title: t('req.col.targetDate'), dataIndex: 'target_date', width: 110, onCell: () => ({ className: 'cell-nowrap' }), render: (v) => v || '-' },
    {
      title: t('req.col.progress'),
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
      title: t('req.col.leadDays'),
      dataIndex: 'lead_days',
      width: 100,
      render: (v: number | null) => (v == null ? '-' : t('req.daysN', { n: v })),
    },
    {
      title: t('comp.pending.col'),
      key: 'pending',
      width: 200,
      render: (_, r) => <PendingStepCell pending={(r as RequirementRow & { pending_step?: PendingStep | null }).pending_step} onGo={() => navigate(`/requirements/${r.id}`)} />,
    },
    // M21：删除（delete 权限，默认仅 admin）：级联移除任务清单与流程记录，示例只读
    ...(canDelete || items.some((item) => item.can_delete)
      ? ([
          {
            title: t('common.actions'),
            key: 'actions',
            width: 70,
            fixed: 'right' as const,
            render: (_: unknown, r: RequirementRow) =>
              r.is_example && !isAdmin ? null : (
                (r.can_delete ?? canDelete) ? (
                <Popconfirm
                  title={t('common.deleteConfirm')}
                  onConfirm={async () => {
                    await api.delete(`/requirements/${r.id}`);
                    message.success(t('common.deleted'));
                    void load();
                  }}
                >
                  <Button type="link" size="small" danger style={{ padding: 0 }}>
                    {t('common.delete')}
                  </Button>
                </Popconfirm>
                ) : null
              ),
          },
        ] as ColumnsType<RequirementRow>)
      : []),
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
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('req.emptyBoard')} style={{ margin: '24px 0' }} />
            ) : (
              rows.map((r) => <BoardCard key={r.id} row={r} onClick={() => navigate(`/requirements/${r.id}`)} />)
            )}
          </div>
        );
      })}
    </div>
  );

  // ----- 需求总览标签内容（原有全部逻辑原样保留） -----
  const overviewTab = (
    <>
      <Space wrap style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}>
        <Space wrap>
          <Segmented
            value={view}
            onChange={(v) => {
              setPage(1);
              setView(v as 'board' | 'table');
            }}
            options={[
              { value: 'table', label: t('req.table'), icon: <TableOutlined /> },
              { value: 'board', label: t('req.board'), icon: <AppstoreOutlined /> },
            ]}
          />
          <Input.Search
            placeholder={t('req.searchPlaceholder')}
            allowClear
            style={{ width: 200 }}
            onSearch={(v) => {
              setPage(1);
              setQ(v);
            }}
          />
          <Select
            placeholder={t('req.domain')}
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
              placeholder={t('common.status')}
              allowClear
              style={{ width: 110 }}
              value={status}
              onChange={(v) => {
                setPage(1);
                setStatus(v);
              }}
              options={STATUS_KEYS.map((s) => ({ value: s, label: et.requirementStatus(s) }))}
            />
          )}
          {view === 'table' && (
            <Select
              placeholder={t('req.decision')}
              allowClear
              style={{ width: 110 }}
              value={decision}
              onChange={(v) => {
                setPage(1);
                setDecision(v);
              }}
              options={REQ_DECISIONS.map((d) => ({ value: d, label: et.reqDecision(d) }))}
            />
          )}
          <span>
            {t('req.mineOnly')}{' '}
            <Switch
              checked={mineOnly}
              onChange={(v) => {
                setPage(1);
                setMineOnly(v);
              }}
            />
          </span>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>
            {t('common.refresh')}
          </Button>
          {view === 'table' && (canDelete || items.some((item) => item.can_delete)) && (
            <BatchDeleteToolbar
              endpoint="/requirements/batch-delete"
              entityName="需求"
              selectedIds={selectedIds}
              onCompleted={() => {
                setSelectedIds([]);
                void load();
              }}
            />
          )}
        </Space>
        {canCreate && (
          <Space>
            <Button icon={<DownloadOutlined />} onClick={() => void api.download('/requirements/template')}>
              {t('req.downloadTemplate')}
            </Button>
            <Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>
              {t('req.import')}
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => openCreate()}>
              {t('req.register')}
            </Button>
          </Space>
        )}
      </Space>

      {view === 'board' ? (
        <Spin spinning={loading}>
          {total > items.length && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message={t('req.boardCapHint', { total, shown: items.length })}
            />
          )}
          {boardView}
        </Spin>
      ) : (
      <Table<RequirementRow>
        className="sticky-table--freeze-columns"
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={items}
          rowSelection={
            canDelete || items.some((item) => item.can_delete)
              ? {
                  selectedRowKeys: selectedIds,
                  onChange: (keys) => setSelectedIds(keys.map(String)),
                  getCheckboxProps: (row) => ({ disabled: !(row.can_delete ?? canDelete) || (!!row.is_example && !isAdmin) }),
                }
              : undefined
          }
          sticky
          scroll={{ x: 'max-content' }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (n) => t('req.totalN', { n }),
            onChange: (p, ps) => {
              setPage(p);
              setPageSize(ps);
            },
          }}
          tableKey="requirements.overview"
          requiredColumnKeys={['requirement_code', 'title', 'actions']}
        />
      )}

      {/* 登记需求 Modal（极简 4+1 字段，30 秒完成） */}
      <Modal
        title={t('req.register')}
        open={createOpen}
        width={560}
        onOk={() => void submitCreate()}
        confirmLoading={saving}
        onCancel={closeCreate}
        destroyOnClose
      >
        <DocumentTypeHint documentType="requirement" />
        <Form<CreateFormValues> form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="title"
            label={t('req.reqTitle')}
            rules={[
              { required: true, message: t('req.reqTitleRequired') },
              { min: 2, message: t('req.min2') },
            ]}
          >
            <Input maxLength={200} placeholder={t('req.titlePlaceholder')} />
          </Form.Item>
          <Form.Item name="req_type" label={t('req.reqType')} rules={[{ required: true, message: t('req.reqTypeRequired') }]}>
            <Select placeholder={t('req.selectType')} options={REQ_TYPES.map((v) => ({ value: v, label: et.reqType(v) }))} />
          </Form.Item>
          <Form.Item
            name="business_domain_id"
            label={t('req.belongDomain')}
            rules={[{ required: true, message: t('req.domainRequired') }]}
          >
            <Select
              showSearch
              optionFilterProp="label"
              placeholder={t('req.selectDomain')}
              options={domains.map((d) => ({ value: d.id, label: d.name }))}
            />
          </Form.Item>
          <Form.Item name="description" label={t('req.reqDesc')} rules={[{ required: true, message: t('req.reqDescRequired') }]}>
            <Input.TextArea rows={4} maxLength={2000} placeholder={t('req.descPlaceholder')} />
          </Form.Item>
          <Form.Item name="other_info" label={t('req.otherInfo')}>
            <Input.TextArea
              rows={3}
              maxLength={1000}
              placeholder={t('req.otherInfoPlaceholder')}
              onPaste={(event) => {
                const files = Array.from(event.clipboardData.files);
                if (files.length === 0) return;
                event.preventDefault();
                files.forEach((file) => void stageRequirementAttachment(file));
              }}
            />
          </Form.Item>
          <Form.Item label={t('req.attachments')} extra={t('req.attachmentHint')}>
            <Space direction="vertical" style={{ width: '100%' }} size={8}>
              <Upload
                multiple
                showUploadList={false}
                beforeUpload={(file) => {
                  void stageRequirementAttachment(file);
                  return Upload.LIST_IGNORE;
                }}
                accept=".png,.jpg,.jpeg,.gif,.webp,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv"
              >
                <Button icon={<PaperClipOutlined />} loading={attachmentUploading > 0}>
                  {t('req.uploadAttachment')}
                </Button>
              </Upload>
              {draftAttachments.length > 0 && (
                <Space wrap size={[8, 8]}>
                  {draftAttachments.map((attachment) => (
                    <Tag
                      key={attachment.id}
                      closable
                      onClose={(event) => {
                        event.preventDefault();
                        void removeDraftAttachment(attachment);
                      }}
                      icon={<PaperClipOutlined />}
                    >
                      {attachment.previewUrl && (
                        <Image
                          preview={{ src: attachment.previewUrl }}
                          src={attachment.previewUrl}
                          width={28}
                          height={28}
                          style={{ objectFit: 'cover', marginRight: 6, verticalAlign: 'middle' }}
                        />
                      )}
                      {attachment.filename}
                    </Tag>
                  ))}
                </Space>
              )}
            </Space>
          </Form.Item>
          <Form.Item name="source" label={t('req.source')}>
            <Select
              allowClear
              placeholder={t('req.selectSource')}
              options={sources.map((s) => ({ value: s.name, label: s.name }))}
            />
          </Form.Item>
          <Collapse
            ghost
            items={[
              {
                key: 'more',
                label: t('req.moreOptions'),
                children: (
                  <>
                    <Form.Item name="expected_date" label={t('req.expectedDate')}>
                      <DatePicker style={{ width: '100%' }} />
                    </Form.Item>
                    <Form.Item name="expected_effect" label={t('req.expectedEffect')}>
                      <Input.TextArea rows={2} maxLength={1000} placeholder={t('req.expectedEffectPlaceholder')} />
                    </Form.Item>
                    <Form.Item name="business_value_note" label={t('req.businessValue')}>
                      <Input.TextArea rows={2} maxLength={1000} placeholder={t('req.businessValuePlaceholder')} />
                    </Form.Item>
                  </>
                ),
              },
            ]}
          />
        </Form>
      </Modal>

      <RequirementImportModal open={importOpen} onClose={() => setImportOpen(false)} onImported={() => void load()} />
    </>
  );

  // M17：任务跟踪/评分规则已拆为左侧导航二级菜单独立页，本页只承载需求总览
  return <Card title={t('req.tab.overview')}><DocumentTypeHint documentType="requirement" />{overviewTab}</Card>;
}
