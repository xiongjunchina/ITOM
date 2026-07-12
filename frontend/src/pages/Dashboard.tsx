import { useEffect, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Button, Card, Col, Empty, List, Row, Space, Spin, Statistic, Tag, Typography } from 'antd';
import {
  AlertOutlined,
  BugOutlined,
  CustomerServiceOutlined,
  FileDoneOutlined,
  FileTextOutlined,
  ProjectOutlined,
  RetweetOutlined,
  SettingOutlined,
  TeamOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { api } from '../api/client';
import { WidgetBoardDrawer, WidgetTitle, useWidgetBoard } from '../components/WidgetBoard';
import type { WidgetDragProps } from '../components/WidgetBoard';
import type { DashboardData } from '../api/types';

const GRAY = 'rgba(0, 0, 0, 0.45)';

/** 总览 widget 注册表：key 有序持久化在个人偏好 preferences.dashboard_widgets（数组顺序=显示顺序） */
const WIDGETS = [
  { key: 'alerts', name: '风险与告警', icon: <AlertOutlined style={{ color: '#ff4d4f' }} /> },
  { key: 'itsm_service_request', name: '服务工单', icon: <FileDoneOutlined style={{ color: '#13c2c2' }} /> },
  { key: 'itsm_change', name: '变更', icon: <RetweetOutlined style={{ color: '#722ed1' }} /> },
  { key: 'itsm_incident', name: '事件', icon: <ThunderboltOutlined style={{ color: '#fa541c' }} /> },
  { key: 'itsm_problem', name: '问题', icon: <BugOutlined style={{ color: '#faad14' }} /> },
  { key: 'service_overview', name: '服务概览', icon: <CustomerServiceOutlined style={{ color: '#1677ff' }} /> },
  { key: 'project', name: '项目', icon: <ProjectOutlined style={{ color: '#2f54eb' }} /> },
  { key: 'requirement', name: '需求', icon: <FileTextOutlined style={{ color: '#eb2f96' }} /> },
  { key: 'team', name: '团队动态', icon: <TeamOutlined style={{ color: '#52c41a' }} /> },
] as const;

type WidgetKey = (typeof WIDGETS)[number]['key'];

/** 按 key 取注册项（卡片标题/图标与注册表保持一致） */
const widgetOf = (key: WidgetKey) => WIDGETS.find((w) => w.key === key) as (typeof WIDGETS)[number];

/** 告警类型 → 标签与颜色（红=风险 / 橙=待办） */
const ALERT_META: Record<string, { label: string; color: string }> = {
  sla_warning: { label: 'SLA 临期', color: 'red' },
  project_red: { label: '项目风险', color: 'red' },
  milestone_overdue: { label: '里程碑逾期', color: 'orange' },
  contract_expiring: { label: '合同临期', color: 'orange' },
  error: { label: '错误', color: 'red' },
  warning: { label: '预警', color: 'orange' },
  info: { label: '提示', color: 'blue' },
};

/** 百分比展示：null 显示 - */
const pct = (v: number | null | undefined) => (v == null ? '-' : `${v}%`);

/** 统一板块卡片：外层容器承接整卡拖拽，标题区为视觉手柄；阴影 + 等高 */
function BlockCard({
  widget,
  extra,
  dragProps,
  children,
}: {
  widget: (typeof WIDGETS)[number];
  extra?: ReactNode;
  dragProps: WidgetDragProps;
  children: ReactNode;
}) {
  const { style, ...handlers } = dragProps;
  return (
    <div {...handlers} style={style}>
      <Card
        title={<WidgetTitle widget={widget} />}
        extra={extra}
        style={{ height: '100%', boxShadow: '0 1px 2px rgba(0,0,0,0.04), 0 2px 8px rgba(0,0,0,0.04)' }}
      >
        {children}
      </Card>
    </div>
  );
}

/** 主指标下方的次要指标（小字） */
function SubStat({ label, value, color }: { label: string; value: ReactNode; color?: string }) {
  return (
    <div style={{ minWidth: 72 }}>
      <div style={{ fontSize: 12, color: GRAY }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 600, color }}>{value}</div>
    </div>
  );
}

/** 次要指标行：与主指标之间用细线分隔 */
const SUB_ROW_STYLE: CSSProperties = {
  display: 'flex',
  gap: 32,
  marginTop: 12,
  paddingTop: 12,
  borderTop: '1px solid rgba(5, 5, 5, 0.06)',
};

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const board = useWidgetBoard(WIDGETS, 'dashboard_widgets');

  useEffect(() => {
    api
      .get<DashboardData>('/dashboard')
      .then(setData)
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" />
      </div>
    );
  }

  const service = data?.service;
  const blocks = service?.itsm_blocks;
  const sr = blocks?.service_request;
  const ch = blocks?.change;
  const inc = blocks?.incident;
  const pb = blocks?.problem;
  const project = data?.project;
  const requirement = data?.requirement;
  const team = data?.team;
  const alerts = data?.alerts ?? [];

  /** 各 widget 渲染器：按偏好数组顺序流式布局（Col 宽度不同，允许换行自然错落） */
  const renderers: Record<WidgetKey, () => ReactNode> = {
    alerts: () => (
      <Col key="alerts" span={24}>
        <BlockCard
          widget={widgetOf('alerts')}
          dragProps={board.dragProps('alerts')}
          extra={alerts.length > 0 ? <Tag color="red">{alerts.length} 项待关注</Tag> : undefined}
        >
          {alerts.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="暂无风险告警，运行平稳"
              style={{ margin: '8px 0' }}
            />
          ) : (
            <List
              size="small"
              dataSource={alerts}
              style={{ maxHeight: 260, overflowY: 'auto' }}
              renderItem={(item) => (
                <List.Item style={{ padding: '6px 0' }}>
                  <Space>
                    <Tag color={ALERT_META[item.type]?.color ?? 'default'}>
                      {ALERT_META[item.type]?.label ?? item.type}
                    </Tag>
                    {item.link ? <Link to={item.link}>{item.title}</Link> : item.title}
                  </Space>
                </List.Item>
              )}
            />
          )}
        </BlockCard>
      </Col>
    ),

    itsm_service_request: () => (
      <Col key="itsm_service_request" xs={24} sm={12} lg={6}>
        <BlockCard
          widget={widgetOf('itsm_service_request')}
          dragProps={board.dragProps('itsm_service_request')}
          extra={<Link to="/itsm/tickets">查看</Link>}
        >
          <Statistic title="待处理" value={sr?.open ?? 0} />
          <div style={SUB_ROW_STYLE}>
            <SubStat label="本月解决" value={sr?.month_resolved ?? 0} />
            <SubStat label="SLA 达成率" value={pct(sr?.sla_rate)} />
          </div>
        </BlockCard>
      </Col>
    ),

    itsm_change: () => (
      <Col key="itsm_change" xs={24} sm={12} lg={6}>
        <BlockCard
          widget={widgetOf('itsm_change')}
          dragProps={board.dragProps('itsm_change')}
          extra={<Link to="/itsm/changes">查看</Link>}
        >
          <Statistic
            title="待审批"
            value={ch?.pending_approval ?? 0}
            valueStyle={(ch?.pending_approval ?? 0) > 0 ? { color: '#fa8c16' } : undefined}
          />
          <div style={SUB_ROW_STYLE}>
            <SubStat label="实施中" value={ch?.implementing ?? 0} />
            <SubStat label="成功率" value={pct(ch?.success_rate)} />
          </div>
        </BlockCard>
      </Col>
    ),

    itsm_incident: () => (
      <Col key="itsm_incident" xs={24} sm={12} lg={6}>
        <BlockCard
          widget={widgetOf('itsm_incident')}
          dragProps={board.dragProps('itsm_incident')}
          extra={<Link to="/itsm/incidents">查看</Link>}
        >
          <Statistic
            title="处理中"
            value={inc?.open ?? 0}
            valueStyle={(inc?.open ?? 0) > 0 ? { color: '#ff4d4f' } : undefined}
          />
          <div style={SUB_ROW_STYLE}>
            <SubStat
              label="SLA 临期"
              value={
                (inc?.sla_warned ?? 0) > 0 ? (
                  <Tag color="red" style={{ marginInlineEnd: 0 }}>
                    {inc?.sla_warned}
                  </Tag>
                ) : (
                  0
                )
              }
            />
            <SubStat label="本月解决" value={inc?.month_resolved ?? 0} />
          </div>
        </BlockCard>
      </Col>
    ),

    itsm_problem: () => (
      <Col key="itsm_problem" xs={24} sm={12} lg={6}>
        <BlockCard
          widget={widgetOf('itsm_problem')}
          dragProps={board.dragProps('itsm_problem')}
          extra={<Link to="/itsm/problems">查看</Link>}
        >
          <Statistic title="进行中" value={pb?.open ?? 0} />
          <div style={SUB_ROW_STYLE}>
            <SubStat label="已知错误" value={pb?.known_errors ?? 0} />
            <SubStat label="关闭率" value={pct(pb?.close_rate)} />
          </div>
        </BlockCard>
      </Col>
    ),

    service_overview: () => (
      <Col key="service_overview" xs={24} lg={8}>
        <BlockCard
          widget={widgetOf('service_overview')}
          dragProps={board.dragProps('service_overview')}
          extra={<Link to="/itsm/sla">查看</Link>}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Statistic title="未关闭工单" value={service?.open_tickets ?? 0} />
              {service?.open_by_priority && (
                <Typography.Text style={{ fontSize: 12 }}>
                  <span style={{ color: '#cf1322', fontWeight: 600 }}>
                    P1 {service.open_by_priority.P1} · P2 {service.open_by_priority.P2}
                  </span>
                  <span style={{ color: GRAY }}>
                    {' '}
                    · P3 {service.open_by_priority.P3} · P4 {service.open_by_priority.P4}
                  </span>
                </Typography.Text>
              )}
            </Col>
            <Col span={12}>
              <Statistic
                title="本月 SLA 达成率"
                value={service?.sla_rate ?? '-'}
                suffix={service?.sla_rate == null ? undefined : '%'}
              />
            </Col>
          </Row>
        </BlockCard>
      </Col>
    ),

    project: () => (
      <Col key="project" xs={24} lg={16}>
        <BlockCard
          widget={widgetOf('project')}
          dragProps={board.dragProps('project')}
          extra={<Link to="/projects">查看</Link>}
        >
          <Row gutter={16}>
            <Col span={6}>
              <Statistic title="进行中项目" value={project?.active ?? 0} />
            </Col>
            <Col span={6}>
              <Statistic
                title="健康度(绿/黄/红)"
                valueRender={() => (
                  <span>
                    <span style={{ color: '#52c41a' }}>{project?.health.green ?? 0}</span>
                    <span style={{ color: 'rgba(0,0,0,0.25)' }}> / </span>
                    <span style={{ color: '#faad14' }}>{project?.health.yellow ?? 0}</span>
                    <span style={{ color: 'rgba(0,0,0,0.25)' }}> / </span>
                    <span style={{ color: '#ff4d4f' }}>{project?.health.red ?? 0}</span>
                  </span>
                )}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="逾期里程碑"
                value={project?.overdue_milestones ?? 0}
                valueStyle={
                  (project?.overdue_milestones ?? 0) > 0 ? { color: '#ff4d4f' } : undefined
                }
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="预算使用率"
                value={project?.budget_usage ?? '-'}
                suffix={project?.budget_usage == null ? undefined : '%'}
                valueStyle={(project?.budget_usage ?? 0) > 100 ? { color: '#ff4d4f' } : undefined}
              />
            </Col>
          </Row>
        </BlockCard>
      </Col>
    ),

    requirement: () => (
      <Col key="requirement" xs={24} lg={12}>
        <BlockCard
          widget={widgetOf('requirement')}
          dragProps={board.dragProps('requirement')}
          extra={<Link to="/requirements">查看</Link>}
        >
          <Row gutter={16}>
            <Col span={5}>
              <Statistic title="已登记" value={requirement?.by_stage.registered ?? 0} />
            </Col>
            <Col span={5}>
              <Statistic title="分析中" value={requirement?.by_stage.analyzing ?? 0} />
            </Col>
            <Col span={5}>
              <Statistic title="实现中" value={requirement?.by_stage.implementing ?? 0} />
            </Col>
            <Col span={4}>
              <Statistic title="已关闭" value={requirement?.by_stage.closed ?? 0} />
            </Col>
            <Col span={5}>
              <Statistic
                title="平均交付周期"
                value={requirement?.avg_lead_days ?? '-'}
                suffix={requirement?.avg_lead_days == null ? undefined : '天'}
              />
            </Col>
          </Row>
        </BlockCard>
      </Col>
    ),

    team: () => (
      <Col key="team" xs={24} lg={12}>
        <BlockCard
          widget={widgetOf('team')}
          dragProps={board.dragProps('team')}
          extra={<Link to="/team/overview">查看</Link>}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Statistic title="本月培训" value={team?.trainings ?? 0} />
            </Col>
            <Col span={12}>
              <Statistic
                title="招聘中"
                value={team?.hirings ?? 0}
                valueStyle={(team?.hirings ?? 0) > 0 ? { color: '#fa8c16' } : undefined}
              />
            </Col>
          </Row>
          <Row gutter={16} style={{ marginTop: 12 }}>
            <Col span={12}>
              <Typography.Text type="secondary">负载 Top5</Typography.Text>
              <List
                size="small"
                dataSource={team?.top_workload ?? []}
                locale={{ emptyText: '暂无数据' }}
                renderItem={(t, i) => (
                  <List.Item style={{ padding: '4px 0' }}>
                    <span>
                      {i + 1}. {t.name}
                    </span>
                    <Typography.Text type="secondary">{t.value}</Typography.Text>
                  </List.Item>
                )}
              />
            </Col>
            <Col span={12}>
              <Typography.Text type="secondary">本期积分 Top5</Typography.Text>
              <List
                size="small"
                dataSource={team?.top_points ?? []}
                locale={{ emptyText: '暂无数据' }}
                renderItem={(t, i) => (
                  <List.Item style={{ padding: '4px 0' }}>
                    <span>
                      {i + 1}. {t.name}
                    </span>
                    <Typography.Text type="secondary">{t.value}</Typography.Text>
                  </List.Item>
                )}
              />
            </Col>
          </Row>
        </BlockCard>
      </Col>
    ),
  };

  return (
    <>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 16,
        }}
      >
        <Typography.Title level={4} style={{ margin: 0 }}>
          运营总览
        </Typography.Title>
        <Button icon={<SettingOutlined />} onClick={board.openCustomize}>
          自定义面板
        </Button>
      </div>

      <Row gutter={[16, 16]}>{(board.orderedKeys as WidgetKey[]).map((k) => renderers[k]())}</Row>

      <WidgetBoardDrawer board={board} description="选择总览页要显示的板块，仅影响当前账号。" />
    </>
  );
}
