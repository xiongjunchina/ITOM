import { periodLabel } from '../../utils/period';
import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Button, Card, Col, Row, Statistic, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import Table from '../../components/SortableTable';
import { FundOutlined, ReloadOutlined, SettingOutlined, TeamOutlined, TrophyOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import { useT } from '../../i18n';
import { WidgetBoardDrawer, WidgetTitle, useWidgetBoard } from '../../components/WidgetBoard';
import type { TeamOverviewData } from '../../api/types';

type WorkloadRow = TeamOverviewData['workload'][number];
type BoardRow = TeamOverviewData['points_board'][number];

/** 团队总览 widget 注册表：key 有序持久化在 preferences.team_overview_widgets（数组顺序=显示顺序） */
const TEAM_WIDGET_META = [
  { key: 'stats', nameKey: 'team.overview.widget.stats', icon: <FundOutlined style={{ color: '#1677ff' }} /> },
  { key: 'workload', nameKey: 'team.overview.widget.workload', icon: <TeamOutlined style={{ color: '#52c41a' }} /> },
  { key: 'points_board', nameKey: 'team.overview.widget.pointsBoard', icon: <TrophyOutlined style={{ color: '#faad14' }} /> },
] as const;

type TeamWidgetKey = (typeof TEAM_WIDGET_META)[number]['key'];

/** 团队总览：关键指标 / 人员负载 / 本期积分榜（widget 化，支持自定义显隐 + 拖拽排序） */
export default function Overview() {
  const t = useT();
  const [data, setData] = useState<TeamOverviewData | null>(null);
  const [loading, setLoading] = useState(true);

  // 注册表 name 按当前语言解析（key/icon 稳定，name 随语言切换）
  const TEAM_WIDGETS = TEAM_WIDGET_META.map((w) => ({ key: w.key, name: t(w.nameKey), icon: w.icon }));
  /** 按 key 取注册项（卡片标题/图标与注册表保持一致） */
  const widgetOf = (key: TeamWidgetKey) =>
    TEAM_WIDGETS.find((w) => w.key === key) as (typeof TEAM_WIDGETS)[number];
  const board = useWidgetBoard(TEAM_WIDGETS, 'team_overview_widgets');

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

  useEffect(() => {
    const timer = window.setInterval(() => void load(), 30_000);
    return () => window.clearInterval(timer);
  }, [load]);

  const workload = data?.workload ?? [];
  const maxTotal = workload.reduce((mx, r) => Math.max(mx, r.total), 0);

  const workloadColumns: ColumnsType<WorkloadRow> = [
    { title: t('team.col.name'), dataIndex: 'person_name', width: 100 },
    { title: t('team.overview.workload.tickets'), dataIndex: 'tickets', width: 70 },
    { title: t('team.overview.workload.wbsTasks'), dataIndex: 'wbs_tasks', width: 90 },
    { title: t('team.overview.workload.reqTasks'), dataIndex: 'req_tasks', width: 90 },
    {
      title: t('team.overview.workload.total'),
      dataIndex: 'total',
      width: 110,
      render: (v: number) =>
        v > 0 && v === maxTotal ? (
          <span>
            <Typography.Text strong style={{ color: '#ff4d4f' }}>
              {v}
            </Typography.Text>
            <Tag color="red" style={{ marginLeft: 8 }}>
              {t('team.overview.workload.highest')}
            </Tag>
          </span>
        ) : (
          v
        ),
    },
  ];

  const boardColumns: ColumnsType<BoardRow> = [
    { title: t('team.col.rank'), key: 'rank', width: 70, render: (_, __, i) => i + 1 },
    { title: t('team.col.name'), dataIndex: 'person_name', render: (v) => v || '-' },
    { title: t('team.col.points'), dataIndex: 'points', width: 90 },
  ];

  /** 各 widget 渲染器：按偏好数组顺序流式布局 */
  const renderers: Record<TeamWidgetKey, () => ReactNode> = {
    stats: () => (
      <Col key="stats" span={24}>
        <div {...board.dragProps('stats')}>
          <Card
            title={<WidgetTitle widget={widgetOf('stats')} />}
            loading={loading}
            style={{ height: '100%' }}
          >
            <Row gutter={[16, 16]}>
              <Col xs={12} lg={6}>
                <Statistic title={t('team.overview.stat.onboard')} value={data?.onboard_count ?? 0} />
              </Col>
              <Col xs={12} lg={6}>
                <Statistic title={t('team.overview.stat.trainingsMonth')} value={data?.trainings_month ?? 0} />
              </Col>
              <Col xs={12} lg={6}>
                <Statistic title={t('team.overview.stat.activeCampaigns')} value={data?.active_campaigns ?? 0} />
              </Col>
              <Col xs={12} lg={6}>
                <Statistic
                  title={t('team.overview.stat.openHirings')}
                  value={data?.open_hirings ?? 0}
                  valueStyle={(data?.open_hirings ?? 0) > 0 ? { color: '#fa8c16' } : undefined}
                />
              </Col>
            </Row>
          </Card>
        </div>
      </Col>
    ),

    workload: () => (
      <Col key="workload" xs={24} lg={14}>
        <div {...board.dragProps('workload')}>
          <Card
            title={<WidgetTitle widget={widgetOf('workload')} suffix={t('team.overview.workload.suffix')} />}
            style={{ height: '100%' }}
          >
            <Table<WorkloadRow>
              rowKey="person_id"
              size="small"
              loading={loading}
              columns={workloadColumns}
              dataSource={workload}
              standardToolbar={{ exportFileName: '团队工作负载', searchPlaceholder: '搜索员工或工作负载' }}
              pagination={false}
              locale={{ emptyText: t('team.overview.workload.empty') }}
            />
          </Card>
        </div>
      </Col>
    ),

    points_board: () => (
      <Col key="points_board" xs={24} lg={10}>
        <div {...board.dragProps('points_board')}>
          <Card
            title={
              <WidgetTitle
                widget={widgetOf('points_board')}
                suffix={`${data?.period ? `（${periodLabel(data.period)}）` : ''} Top10`}
              />
            }
            style={{ height: '100%' }}
          >
            <Table<BoardRow>
              rowKey={(r, i) => `${i}-${r.person_name ?? ''}`}
              size="small"
              loading={loading}
              columns={boardColumns}
              dataSource={data?.points_board ?? []}
              standardToolbar={{ exportFileName: '团队积分排行榜', searchPlaceholder: '搜索员工或积分' }}
              pagination={false}
              locale={{ emptyText: t('team.overview.board.empty') }}
            />
          </Card>
        </div>
      </Col>
    ),
  };

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginBottom: 16 }}>
        <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>
          {t('common.refresh')}
        </Button>
        <Button icon={<SettingOutlined />} onClick={board.openCustomize}>
          {t('team.overview.customize')}
        </Button>
      </div>

      <Row gutter={[16, 16]}>
        {(board.orderedKeys as TeamWidgetKey[]).map((k) => renderers[k]())}
      </Row>

      <WidgetBoardDrawer board={board} description={t('team.overview.boardDesc')} />
    </>
  );
}
