import { useCallback, useEffect, useState } from 'react';
import { Card, Input, Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { api } from '../../api/client';
import type { AuditLog } from '../../api/types';

const ACTION_COLORS: Record<string, string> = {
  create: 'green',
  update: 'blue',
  delete: 'red',
};

export default function AuditLogs() {
  const [items, setItems] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [entityType, setEntityType] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<AuditLog>('/admin/audit-logs', {
        page,
        page_size: pageSize,
        entity_type: entityType || undefined,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, entityType]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns: ColumnsType<AuditLog> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-'),
    },
    { title: '实体类型', dataIndex: 'entity_type', width: 130 },
    { title: '实体 ID', dataIndex: 'entity_id', width: 100 },
    {
      title: '动作',
      dataIndex: 'action',
      width: 100,
      render: (v: string) => <Tag color={ACTION_COLORS[v] ?? 'default'}>{v}</Tag>,
    },
    { title: '操作人', dataIndex: 'actor_name', width: 120 },
    { title: '摘要', dataIndex: 'summary', ellipsis: true },
  ];

  return (
    <Card
      title="审计日志"
      extra={
        <Input.Search
          placeholder="按实体类型筛选，如 user / member"
          allowClear
          onSearch={(v) => {
            setPage(1);
            setEntityType(v.trim());
          }}
          style={{ width: 280 }}
        />
      }
    >
      <Table<AuditLog>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
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
