import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Button, Card, Input, Popconfirm, Select, Space, Tag, Upload, message } from 'antd';
import type { UploadProps } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import Table from '../../components/SortableTable';
import { EditOutlined, EyeOutlined, ImportOutlined, LikeOutlined, ReloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from '../../api/client';
import { ExampleTag } from '../../components/ExampleTag';
import { hasPermission, useAuthStore } from '../../stores/auth';
import { useT } from '../../i18n';
import type { KnowledgeImportResult, KnowledgeRow, KnowledgeStatus } from '../../api/types';

export default function Knowledge() {
  const navigate = useNavigate();
  const t = useT();
  const user = useAuthStore((s) => s.user);
  const canDelete = hasPermission(user, 'knowledge', 'delete'); // M21：默认矩阵仅 admin
  const isAdmin = !!user?.permissions?.['*'];
  const [items, setItems] = useState<KnowledgeRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<KnowledgeStatus | undefined>();
  const [importing, setImporting] = useState(false);

  /** 文档导入（.docx/.md/.html/.txt）：成功创建草稿后跳转详情供审阅发布 */
  const importDocRequest: NonNullable<UploadProps['customRequest']> = ({ file, onSuccess, onError }) => {
    setImporting(true);
    api
      .upload<KnowledgeImportResult>('/knowledge/import', file as File)
      .then((res) => {
        message.success(t('itsm.kb.imported', { title: res.title }));
        onSuccess?.(res);
        navigate(`/itsm/knowledge/${res.article_id}`);
      })
      .catch((e) => {
        // 已统一提示（IMPORT_FAILED 等）
        onError?.(e as Error);
      })
      .finally(() => setImporting(false));
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<KnowledgeRow>('/knowledge', {
        page,
        page_size: pageSize,
        q: q || undefined,
        status: status || undefined,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, q, status]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns: ColumnsType<KnowledgeRow> = [
    {
      title: t('itsm.f.code'),
      dataIndex: 'article_code',
      width: 140,
      fixed: 'left',
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (v: string, r) => <Link to={`/itsm/knowledge/${r.id}`}>{v}</Link>,
    },
    {
      title: t('itsm.f.title'),
      dataIndex: 'title',
      width: 280,
      ellipsis: true,
      render: (v: string, r) => (
        <Space size={4}>
          <Link to={`/itsm/knowledge/${r.id}`}>{v}</Link>
          {r.is_example && <ExampleTag />}
        </Space>
      ),
    },
    {
      title: t('itsm.f.tags'),
      dataIndex: 'tags',
      width: 200,
      render: (tags: string[]) =>
        tags?.length ? (
          <Space size={4} wrap>
            {tags.map((tag) => (
              <Tag key={tag}>{tag}</Tag>
            ))}
          </Space>
        ) : (
          '-'
        ),
    },
    {
      title: t('common.status'),
      dataIndex: 'status',
      width: 90,
      render: (v: KnowledgeStatus) =>
        v === 'draft' ? <Tag color="default">{t('itsm.kb.draft')}</Tag> : <Tag color="green">{t('itsm.kb.published')}</Tag>,
    },
    { title: t('itsm.f.author'), dataIndex: 'author_name', width: 100, render: (v) => v || '-' },
    {
      title: (
        <span>
          <EyeOutlined /> {t('itsm.kb.views')}
        </span>
      ),
      dataIndex: 'view_count',
      width: 90,
      align: 'right',
    },
    {
      title: (
        <span>
          <LikeOutlined /> {t('itsm.kb.helpful')}
        </span>
      ),
      dataIndex: 'helpful_count',
      width: 90,
      align: 'right',
    },
    {
      title: t('itsm.f.updatedAt'),
      dataIndex: 'updated_at',
      width: 150,
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'),
    },
    // M21：删除（delete 权限，默认仅 admin），示例数据只读
    ...(canDelete
      ? ([
          {
            title: t('common.actions'),
            key: 'actions',
            width: 70,
            fixed: 'right' as const,
            render: (_: unknown, r: KnowledgeRow) =>
              r.is_example && !isAdmin ? null : (
                <Popconfirm
                  title={t('common.deleteConfirm')}
                  onConfirm={async () => {
                    await api.delete(`/knowledge/${r.id}`);
                    message.success(t('common.deleted'));
                    void load();
                  }}
                >
                  <Button type="link" size="small" danger style={{ padding: 0 }}>
                    {t('common.delete')}
                  </Button>
                </Popconfirm>
              ),
          },
        ] as ColumnsType<KnowledgeRow>)
      : []),
  ];

  return (
    <Card
      title={t('itsm.kb.title')}
      extra={
        <Button type="primary" icon={<EditOutlined />} onClick={() => navigate('/itsm/knowledge/new')}>
          {t('itsm.kb.write')}
        </Button>
      }
    >
      <Space wrap style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder={t('itsm.kb.searchPlaceholder')}
          allowClear
          style={{ width: 240 }}
          onSearch={(v) => {
            setPage(1);
            setQ(v);
          }}
        />
        <Select
          placeholder={t('common.status')}
          allowClear
          style={{ width: 120 }}
          value={status}
          onChange={(v) => {
            setPage(1);
            setStatus(v);
          }}
          options={[
            { value: 'published', label: t('itsm.kb.published') },
            { value: 'draft', label: t('itsm.kb.draft') },
          ]}
        />
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>
          {t('common.refresh')}
        </Button>
        <Upload
          accept=".docx,.md,.markdown,.html,.htm,.txt"
          showUploadList={false}
          customRequest={importDocRequest}
          disabled={importing}
        >
          <Button icon={<ImportOutlined />} loading={importing}>
            {t('itsm.kb.importDoc')}
          </Button>
        </Upload>
      </Space>

      <Table<KnowledgeRow>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        standardToolbar={{ exportFileName: '知识库清单', showSearch: false, showFilter: false }}
        sticky
        scroll={{ x: 1150 }}
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
    </Card>
  );
}
