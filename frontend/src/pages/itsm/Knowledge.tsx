import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Button, Card, Input, Select, Space, Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { EditOutlined, EyeOutlined, LikeOutlined, ReloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from '../../api/client';
import type { KnowledgeRow, KnowledgeStatus } from '../../api/types';

export default function Knowledge() {
  const navigate = useNavigate();
  const [items, setItems] = useState<KnowledgeRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<KnowledgeStatus | undefined>();

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
      title: '编号',
      dataIndex: 'article_code',
      width: 120,
      fixed: 'left',
      render: (v: string, r) => <Link to={`/itsm/knowledge/${r.id}`}>{v}</Link>,
    },
    {
      title: '标题',
      dataIndex: 'title',
      width: 280,
      ellipsis: true,
      render: (v: string, r) => <Link to={`/itsm/knowledge/${r.id}`}>{v}</Link>,
    },
    {
      title: '标签',
      dataIndex: 'tags',
      width: 200,
      render: (tags: string[]) =>
        tags?.length ? (
          <Space size={4} wrap>
            {tags.map((t) => (
              <Tag key={t}>{t}</Tag>
            ))}
          </Space>
        ) : (
          '-'
        ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: KnowledgeStatus) =>
        v === 'draft' ? <Tag color="default">草稿</Tag> : <Tag color="green">已发布</Tag>,
    },
    { title: '作者', dataIndex: 'author_name', width: 100, render: (v) => v || '-' },
    {
      title: (
        <span>
          <EyeOutlined /> 浏览
        </span>
      ),
      dataIndex: 'view_count',
      width: 90,
      align: 'right',
    },
    {
      title: (
        <span>
          <LikeOutlined /> 有用
        </span>
      ),
      dataIndex: 'helpful_count',
      width: 90,
      align: 'right',
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 150,
      render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'),
    },
  ];

  return (
    <Card
      title="知识库"
      extra={
        <Button type="primary" icon={<EditOutlined />} onClick={() => navigate('/itsm/knowledge/new')}>
          写文章
        </Button>
      }
    >
      <Space wrap style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="搜索标题/内容"
          allowClear
          style={{ width: 240 }}
          onSearch={(v) => {
            setPage(1);
            setQ(v);
          }}
        />
        <Select
          placeholder="状态"
          allowClear
          style={{ width: 120 }}
          value={status}
          onChange={(v) => {
            setPage(1);
            setStatus(v);
          }}
          options={[
            { value: 'published', label: '已发布' },
            { value: 'draft', label: '草稿' },
          ]}
        />
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>
          刷新
        </Button>
      </Space>

      <Table<KnowledgeRow>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        scroll={{ x: 1150 }}
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
    </Card>
  );
}
