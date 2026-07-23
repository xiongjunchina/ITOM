import { useCallback, useEffect, useState } from 'react';
import { Card, Input, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { api } from '../../api/client';
import { useT } from '../../i18n';
import type { AuditLog } from '../../api/types';
import Table from '../../components/SortableTable';

const ACTION_COLORS: Record<string, string> = {
  create: 'green',
  update: 'blue',
  delete: 'red',
};

export default function AuditLogs() {
  const t = useT();
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
      title: t('admin.audit.time'),
      dataIndex: 'created_at',
      width: 170,
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-'),
    },
    { title: t('admin.audit.entityType'), dataIndex: 'entity_type', width: 130 },
    { title: t('admin.audit.entityId'), dataIndex: 'entity_id', width: 100, ellipsis: true },
    {
      title: t('admin.audit.action'),
      dataIndex: 'action',
      width: 100,
      render: (v: string) => <Tag color={ACTION_COLORS[v] ?? 'default'}>{v}</Tag>,
    },
    { title: t('admin.audit.actor'), dataIndex: 'actor_name', width: 120 },
    { title: t('admin.audit.summary'), dataIndex: 'summary', ellipsis: true },
  ];

  return (
    <Card
      title={t('admin.audit.title')}
      extra={
        <Input.Search
          placeholder={t('admin.audit.filterPlaceholder')}
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
        standardToolbar={{ exportFileName: '审计日志', showSearch: false, showFilter: false }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (n) => t('admin.total', { n }),
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
      />
    </Card>
  );
}
