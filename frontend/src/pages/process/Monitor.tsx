import { useCallback, useEffect, useState } from 'react';
import { Button, Card, Select, Space, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ReloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from '../../api/client';
import type { ProcessInstanceRow } from '../../api/types';
import { PROCESS_ENTITY_LABELS, PROCESS_INSTANCE_STATUS } from '../../api/types';

const fmtTime = (v?: string | null) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-');

/** 流程监控：实例列表 + 当前卡点步骤 + 超时标记 */
export default function Monitor() {
  const [items, setItems] = useState<ProcessInstanceRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);

  const [status, setStatus] = useState<string | undefined>();
  const [entityType, setEntityType] = useState<string | undefined>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<ProcessInstanceRow>('/process-instances', {
        page,
        page_size: pageSize,
        status: status || undefined,
        entity_type: entityType || undefined,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, status, entityType]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns: ColumnsType<ProcessInstanceRow> = [
    { title: '流程名', dataIndex: 'definition_name', width: 200, ellipsis: true },
    {
      title: '实体类型',
      dataIndex: 'entity_type',
      width: 90,
      render: (v: string) => PROCESS_ENTITY_LABELS[v] ?? v,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => {
        const meta = PROCESS_INSTANCE_STATUS[v];
        return <Tag color={meta?.color ?? 'default'}>{meta?.label ?? v}</Tag>;
      },
    },
    { title: '当前步骤', dataIndex: 'current_step', width: 150, ellipsis: true, render: (v) => v || '-' },
    { title: '当前处理人', dataIndex: 'current_assignee', width: 110, render: (v) => v || '-' },
    {
      title: '截止时间',
      dataIndex: 'current_due_at',
      width: 180,
      render: (v: string | null, r) =>
        v ? (
          <Space size={4}>
            <Typography.Text style={r.overdue ? { color: '#ff4d4f' } : undefined}>
              {fmtTime(v)}
            </Typography.Text>
            {r.overdue && <Tag color="red">已超时</Tag>}
          </Space>
        ) : (
          '-'
        ),
    },
    { title: '发起时间', dataIndex: 'started_at', width: 150, render: (v: string) => fmtTime(v) },
    { title: '完成时间', dataIndex: 'completed_at', width: 150, render: (v: string | null) => fmtTime(v) },
  ];

  return (
    <Card title="流程监控">
      <Space wrap style={{ marginBottom: 16 }}>
        <Select
          placeholder="状态"
          allowClear
          style={{ width: 130 }}
          value={status}
          onChange={(v) => {
            setPage(1);
            setStatus(v);
          }}
          options={Object.entries(PROCESS_INSTANCE_STATUS).map(([value, meta]) => ({
            value,
            label: meta.label,
          }))}
        />
        <Select
          placeholder="实体类型"
          allowClear
          style={{ width: 130 }}
          value={entityType}
          onChange={(v) => {
            setPage(1);
            setEntityType(v);
          }}
          options={Object.entries(PROCESS_ENTITY_LABELS).map(([value, label]) => ({ value, label }))}
        />
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>
          刷新
        </Button>
      </Space>

      <Table<ProcessInstanceRow>
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
    </Card>
  );
}
