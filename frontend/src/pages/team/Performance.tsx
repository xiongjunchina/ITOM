import { useCallback, useEffect, useState } from 'react';
import { Alert, Card, Result, Select, Space, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { api } from '../../api/client';
import { currentPeriod, recentPeriods } from '../../utils/period';
import type { PerformanceData, PerformanceRow } from '../../api/types';
import { POINT_SOURCE_LABELS } from '../../api/types';

/** 人效评分（框架 v1）：自动积分 + 专项活动折算分，正式公式待产品定义 */
export default function Performance() {
  const [period, setPeriod] = useState(currentPeriod());
  const [data, setData] = useState<PerformanceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.get<PerformanceData>('/team/performance', { period }));
    } catch (e) {
      const status = (e as { response?: { status?: number } })?.response?.status;
      if (status === 403) setForbidden(true);
    } finally {
      setLoading(false);
    }
  }, [period]);

  useEffect(() => {
    void load();
  }, [load]);

  if (forbidden) {
    return (
      <Card>
        <Result status="403" title="无权限" subTitle="您没有人效评分的查看权限，请联系管理员开通。" />
      </Card>
    );
  }

  const columns: ColumnsType<PerformanceRow> = [
    { title: '姓名', dataIndex: 'person_name', width: 100, fixed: 'left' },
    { title: '自动积分', dataIndex: 'auto_points', width: 90 },
    { title: '活动积分', dataIndex: 'campaign_points', width: 90 },
    { title: '活动折算绩效', dataIndex: 'campaign_performance', width: 110 },
    {
      title: '总分',
      dataIndex: 'total_score',
      width: 100,
      render: (v: number) => <Typography.Text strong>{v}</Typography.Text>,
    },
    {
      title: '积分构成（自动积分维度 × 次数）',
      dataIndex: 'dimensions',
      render: (dims: Record<string, number>) =>
        Object.keys(dims).length > 0 ? (
          <Space size={4} wrap>
            {Object.entries(dims).map(([k, n]) => (
              <Tag key={k}>{`${POINT_SOURCE_LABELS[k] ?? k}×${n}`}</Tag>
            ))}
          </Space>
        ) : (
          '-'
        ),
    },
  ];

  return (
    <Card
      title="人效评分"
      extra={
        <Select
          value={period}
          style={{ width: 130 }}
          onChange={setPeriod}
          options={recentPeriods(2).map((p) => ({ value: p, label: p }))}
        />
      }
    >
      {data?.formula && (
        <Alert type="info" showIcon style={{ marginBottom: 16 }} message={data.formula} />
      )}
      <Table<PerformanceRow>
        rowKey="person_id"
        loading={loading}
        columns={columns}
        dataSource={data?.rows ?? []}
        scroll={{ x: 900 }}
        pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 人` }}
      />
    </Card>
  );
}
