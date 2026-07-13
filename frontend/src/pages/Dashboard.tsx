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
import type { WidgetDragProps, WidgetMeta } from '../components/WidgetBoard';
import { useT } from '../i18n';
import type { DashboardData } from '../api/types';

const GRAY = 'rgba(0, 0, 0, 0.45)';

/** 总览 widget 注册表 key（有序持久化在个人偏好 preferences.dashboard_widgets，数组顺序=显示顺序）；显示名在组件内 t('dash.widget.*') 渲染 */
const WIDGET_KEYS = [
  'alerts',
  'itsm_service_request',
  'itsm_change',
  'itsm_incident',
  'itsm_problem',
  'service_overview',
  'project',
  'requirement',
  'team',
] as const;

type WidgetKey = (typeof WIDGET_KEYS)[number];

/** 各 widget 图标（与语言无关，稳定注册表） */
const WIDGET_ICONS: Record<WidgetKey, ReactNode> = {
  alerts: <AlertOutlined style={{ color: '#ff4d4f' }} />,
  itsm_service_request: <FileDoneOutlined style={{ color: '#13c2c2' }} />,
  itsm_change: <RetweetOutlined style={{ color: '#722ed1' }} />,
  itsm_incident: <ThunderboltOutlined style={{ color: '#fa541c' }} />,
  itsm_problem: <BugOutlined style={{ color: '#faad14' }} />,
  service_overview: <CustomerServiceOutlined style={{ color: '#1677ff' }} />,
  project: <ProjectOutlined style={{ color: '#2f54eb' }} />,
  requirement: <FileTextOutlined style={{ color: '#eb2f96' }} />,
  team: <TeamOutlined style={{ color: '#52c41a' }} />,
};

/** 告警类型 → 颜色（红=风险 / 橙=待办；标签在组件内 t('dash.alert.*') 渲染） */
const ALERT_COLOR: Record<string, string> = {
  sla_warning: 'red',
  project_red: 'red',
  milestone_overdue: 'orange',
  contract_expiring: 'orange',
  error: 'red',
  warning: 'orange',
  info: 'blue',
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
  widget: WidgetMeta;
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
  const t = useT();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  /** widget 注册表：图标稳定 + 显示名随语言 t 渲染 */
  const WIDGETS: WidgetMeta[] = WIDGET_KEYS.map((key) => ({
    key,
    name: t('dash.widget.' + key),
    icon: WIDGET_ICONS[key],
  }));
  /** 按 key 取注册项（卡片标题/图标与注册表保持一致） */
  const widgetOf = (key: WidgetKey) => WIDGETS.find((w) => w.key === key) as WidgetMeta;
  /** 告警类型标签：已知类型走 t，未知回退原始 type */
  const alertLabel = (type: string) => (ALERT_COLOR[type] ? t('dash.alert.' + type) : type);

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
          extra={alerts.length > 0 ? <Tag color="red">{t('dash.alertsCount', { n: alerts.length })}</Tag> : undefined}
        >
          {alerts.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t('dash.noAlerts')}
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
                    <Tag color={ALERT_COLOR[item.type] ?? 'default'}>
                      {alertLabel(item.type)}
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
          extra={<Link to="/itsm/tickets">{t('dash.view')}</Link>}
        >
          <Statistic title={t('dash.sr.open')} value={sr?.open ?? 0} />
          <div style={SUB_ROW_STYLE}>
            <SubStat label={t('dash.sr.monthResolved')} value={sr?.month_resolved ?? 0} />
            <SubStat label={t('dash.sr.slaRate')} value={pct(sr?.sla_rate)} />
          </div>
        </BlockCard>
      </Col>
    ),

    itsm_change: () => (
      <Col key="itsm_change" xs={24} sm={12} lg={6}>
        <BlockCard
          widget={widgetOf('itsm_change')}
          dragProps={board.dragProps('itsm_change')}
          extra={<Link to="/itsm/changes">{t('dash.view')}</Link>}
        >
          <Statistic
            title={t('dash.change.pending')}
            value={ch?.pending_approval ?? 0}
            valueStyle={(ch?.pending_approval ?? 0) > 0 ? { color: '#fa8c16' } : undefined}
          />
          <div style={SUB_ROW_STYLE}>
            <SubStat label={t('dash.change.implementing')} value={ch?.implementing ?? 0} />
            <SubStat label={t('dash.change.successRate')} value={pct(ch?.success_rate)} />
          </div>
        </BlockCard>
      </Col>
    ),

    itsm_incident: () => (
      <Col key="itsm_incident" xs={24} sm={12} lg={6}>
        <BlockCard
          widget={widgetOf('itsm_incident')}
          dragProps={board.dragProps('itsm_incident')}
          extra={<Link to="/itsm/incidents">{t('dash.view')}</Link>}
        >
          <Statistic
            title={t('dash.incident.open')}
            value={inc?.open ?? 0}
            valueStyle={(inc?.open ?? 0) > 0 ? { color: '#ff4d4f' } : undefined}
          />
          <div style={SUB_ROW_STYLE}>
            <SubStat
              label={t('dash.incident.slaWarn')}
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
            <SubStat label={t('dash.incident.monthResolved')} value={inc?.month_resolved ?? 0} />
          </div>
        </BlockCard>
      </Col>
    ),

    itsm_problem: () => (
      <Col key="itsm_problem" xs={24} sm={12} lg={6}>
        <BlockCard
          widget={widgetOf('itsm_problem')}
          dragProps={board.dragProps('itsm_problem')}
          extra={<Link to="/itsm/problems">{t('dash.view')}</Link>}
        >
          <Statistic title={t('dash.problem.open')} value={pb?.open ?? 0} />
          <div style={SUB_ROW_STYLE}>
            <SubStat label={t('dash.problem.knownErrors')} value={pb?.known_errors ?? 0} />
            <SubStat label={t('dash.problem.closeRate')} value={pct(pb?.close_rate)} />
          </div>
        </BlockCard>
      </Col>
    ),

    service_overview: () => (
      <Col key="service_overview" xs={24} lg={8}>
        <BlockCard
          widget={widgetOf('service_overview')}
          dragProps={board.dragProps('service_overview')}
          extra={<Link to="/itsm/sla">{t('dash.view')}</Link>}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Statistic title={t('dash.service.openTickets')} value={service?.open_tickets ?? 0} />
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
                title={t('dash.service.slaRate')}
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
          extra={<Link to="/projects">{t('dash.view')}</Link>}
        >
          <Row gutter={16}>
            <Col span={6}>
              <Statistic title={t('dash.project.active')} value={project?.active ?? 0} />
            </Col>
            <Col span={6}>
              <Statistic
                title={t('dash.project.health')}
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
                title={t('dash.project.overdueMs')}
                value={project?.overdue_milestones ?? 0}
                valueStyle={
                  (project?.overdue_milestones ?? 0) > 0 ? { color: '#ff4d4f' } : undefined
                }
              />
            </Col>
            <Col span={6}>
              <Statistic
                title={t('dash.project.budget')}
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
          extra={<Link to="/requirements">{t('dash.view')}</Link>}
        >
          <Row gutter={16}>
            <Col span={4}>
              <Statistic title={t('dash.req.registered')} value={requirement?.by_stage.registered ?? 0} />
            </Col>
            <Col span={4}>
              <Statistic title={t('dash.req.evaluating')} value={requirement?.by_stage.evaluating ?? 0} />
            </Col>
            <Col span={4}>
              <Statistic title={t('dash.req.analyzing')} value={requirement?.by_stage.analyzing ?? 0} />
            </Col>
            <Col span={4}>
              <Statistic title={t('dash.req.implementing')} value={requirement?.by_stage.implementing ?? 0} />
            </Col>
            <Col span={4}>
              <Statistic title={t('dash.req.closed')} value={requirement?.by_stage.closed ?? 0} />
            </Col>
            <Col span={4}>
              <Statistic
                title={t('dash.req.avgLead')}
                value={requirement?.avg_lead_days ?? '-'}
                suffix={requirement?.avg_lead_days == null ? undefined : t('dash.days')}
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
          extra={<Link to="/team/overview">{t('dash.view')}</Link>}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Statistic title={t('dash.team.trainings')} value={team?.trainings ?? 0} />
            </Col>
            <Col span={12}>
              <Statistic
                title={t('dash.team.hirings')}
                value={team?.hirings ?? 0}
                valueStyle={(team?.hirings ?? 0) > 0 ? { color: '#fa8c16' } : undefined}
              />
            </Col>
          </Row>
          <Row gutter={16} style={{ marginTop: 12 }}>
            <Col span={12}>
              <Typography.Text type="secondary">{t('dash.team.topWorkload')}</Typography.Text>
              <List
                size="small"
                dataSource={team?.top_workload ?? []}
                locale={{ emptyText: t('common.noData') }}
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
              <Typography.Text type="secondary">{t('dash.team.topPoints')}</Typography.Text>
              <List
                size="small"
                dataSource={team?.top_points ?? []}
                locale={{ emptyText: t('common.noData') }}
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
          {t('dash.title')}
        </Typography.Title>
        <Button icon={<SettingOutlined />} onClick={board.openCustomize}>
          {t('dash.customize')}
        </Button>
      </div>

      <Row gutter={[16, 16]}>{(board.orderedKeys as WidgetKey[]).map((k) => renderers[k]())}</Row>

      <WidgetBoardDrawer board={board} description={t('dash.boardDesc')} />
    </>
  );
}
