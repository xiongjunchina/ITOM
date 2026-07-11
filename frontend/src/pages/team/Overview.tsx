import { useCallback, useEffect, useState } from 'react';
import { Card, Col, Row, Statistic, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { api } from '../../api/client';
import type { TeamOverviewData } from '../../api/types';

type WorkloadRow = TeamOverviewData['workload'][number];
type BoardRow = TeamOverviewData['points_board'][number];

/** 团队总览：人数/培训/活动/招聘统计 + 人员负载 + 本期积分榜 */
export default function Overview() {
  const [data, setData] = useState<TeamOverviewData | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.get<TeamOverviewData>('/team/overview'));
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const workload = data?.workload ?? [];
  const maxTotal = workload.reduce((mx, r) => Math.max(mx, r.total), 0);

  const workloadColumns: ColumnsType<WorkloadRow> = [
    { title: '姓名', dataIndex: 'person_name', width: 100 },
    { title: '工单', dataIndex: 'tickets', width: 70 },
    { title: '项目任务', dataIndex: 'wbs_tasks', width: 90 },
    { title: '需求任务', dataIndex: 'req_tasks', width: 90 },
    {
      title: '合计',
      dataIndex: 'total',
      width: 110,
      render: (v: number) =>
        v > 0 && v === maxTotal ? (
          <span>
            <Typography.Text strong style={{ color: '#ff4d4f' }}>
              {v}
            </Typography.Text>
            <Tag color="red" style={{ marginLeft: 8 }}>
              负载最高
            </Tag>
          </span>
        ) : (
          v
        ),
    },
  ];

  const boardColumns: ColumnsType<BoardRow> = [
    { title: '名次', key: 'rank', width: 70, render: (_, __, i) => i + 1 },
    { title: '姓名', dataIndex: 'person_name', render: (v) => v || '-' },
    { title: '积分', dataIndex: 'points', width: 90 },
  ];

  return (
    <Row gutter={[16, 16]}>
      <Col xs={12} lg={6}>
        <Card loading={loading}>
          <Statistic title="在岗人数" value={data?.onboard_count ?? 0} />
        </Card>
      </Col>
      <Col xs={12} lg={6}>
        <Card loading={loading}>
          <Statistic title="本月培训" value={data?.trainings_month ?? 0} />
        </Card>
      </Col>
      <Col xs={12} lg={6}>
        <Card loading={loading}>
          <Statistic title="进行中专项活动" value={data?.active_campaigns ?? 0} />
        </Card>
      </Col>
      <Col xs={12} lg={6}>
        <Card loading={loading}>
          <Statistic
            title="待招聘"
            value={data?.open_hirings ?? 0}
            valueStyle={(data?.open_hirings ?? 0) > 0 ? { color: '#fa8c16' } : undefined}
          />
        </Card>
      </Col>

      <Col xs={24} lg={14}>
        <Card title="人员负载（未完成事项，按合计降序）">
          <Table<WorkloadRow>
            rowKey="person_id"
            size="small"
            loading={loading}
            columns={workloadColumns}
            dataSource={workload}
            pagination={false}
            locale={{ emptyText: '暂无在岗人员负载数据' }}
          />
        </Card>
      </Col>
      <Col xs={24} lg={10}>
        <Card title={`本期积分榜${data?.period ? `（${data.period}）` : ''} Top10`}>
          <Table<BoardRow>
            rowKey={(r, i) => `${i}-${r.person_name ?? ''}`}
            size="small"
            loading={loading}
            columns={boardColumns}
            dataSource={data?.points_board ?? []}
            pagination={false}
            locale={{ emptyText: '本期暂无积分记录' }}
          />
        </Card>
      </Col>
    </Row>
  );
}
