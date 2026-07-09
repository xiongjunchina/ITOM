import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Card, Col, List, Row, Spin, Statistic, Tag, Typography } from 'antd';
import {
  AlertOutlined,
  CustomerServiceOutlined,
  FileTextOutlined,
  ProjectOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import { api } from '../api/client';
import type { DashboardData } from '../api/types';

const ALERT_COLORS: Record<string, string> = {
  error: 'red',
  warning: 'orange',
  info: 'blue',
};

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);

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
  const project = data?.project;
  const requirement = data?.requirement;
  const team = data?.team;
  const alerts = data?.alerts ?? [];

  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={12}>
        <Card
          title={
            <span>
              <CustomerServiceOutlined /> 服务
            </span>
          }
        >
          <Row gutter={16}>
            <Col span={8}>
              <Statistic title="未关闭工单" value={service?.open_tickets ?? 0} />
              {service?.open_by_priority && (
                <Typography.Text style={{ fontSize: 12 }}>
                  <span style={{ color: '#cf1322', fontWeight: 600 }}>
                    P1 {service.open_by_priority.P1} · P2 {service.open_by_priority.P2}
                  </span>
                  <span style={{ color: 'rgba(0,0,0,0.45)' }}>
                    {' '}
                    · P3 {service.open_by_priority.P3} · P4 {service.open_by_priority.P4}
                  </span>
                </Typography.Text>
              )}
            </Col>
            <Col span={8}>
              <Statistic title="SLA 达成率" value={service?.sla_rate ?? 0} suffix="%" />
            </Col>
            <Col span={8}>
              <Statistic title="变更成功率" value={service?.change_success_rate ?? 0} suffix="%" />
            </Col>
          </Row>
        </Card>
      </Col>
      <Col xs={24} lg={12}>
        <Card
          title={
            <span>
              <ProjectOutlined /> 项目
            </span>
          }
        >
          <Row gutter={16}>
            <Col span={6}>
              <Statistic title="进行中项目" value={project?.active ?? 0} />
            </Col>
            <Col span={6}>
              <Statistic
                title="健康度(绿/黄/红)"
                value={`${project?.health.green ?? 0} / ${project?.health.yellow ?? 0} / ${project?.health.red ?? 0}`}
              />
            </Col>
            <Col span={6}>
              <Statistic title="逾期里程碑" value={project?.overdue_milestones ?? 0} />
            </Col>
            <Col span={6}>
              <Statistic title="预算使用率" value={project?.budget_usage ?? 0} suffix="%" />
            </Col>
          </Row>
        </Card>
      </Col>
      <Col xs={24} lg={12}>
        <Card
          title={
            <span>
              <FileTextOutlined /> 需求
            </span>
          }
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
              <Statistic title="平均交付周期" value={requirement?.avg_lead_days ?? 0} suffix="天" />
            </Col>
          </Row>
        </Card>
      </Col>
      <Col xs={24} lg={12}>
        <Card
          title={
            <span>
              <TeamOutlined /> 团队
            </span>
          }
        >
          <Row gutter={16}>
            <Col span={6}>
              <Statistic title="进行中培训" value={team?.trainings ?? 0} />
            </Col>
            <Col span={6}>
              <Statistic title="招聘需求" value={team?.hirings ?? 0} />
            </Col>
            <Col span={6}>
              <Statistic title="负载 TOP" value={team?.top_workload?.length ?? 0} suffix="人" />
            </Col>
            <Col span={6}>
              <Statistic title="积分 TOP" value={team?.top_points?.length ?? 0} suffix="人" />
            </Col>
          </Row>
          {(team?.top_workload?.length ?? 0) > 0 && (
            <Typography.Paragraph style={{ marginTop: 12, marginBottom: 0 }} type="secondary">
              负载 TOP：{team?.top_workload.map((t) => `${t.name}(${t.value})`).join('、')}
            </Typography.Paragraph>
          )}
          {(team?.top_points?.length ?? 0) > 0 && (
            <Typography.Paragraph style={{ marginTop: 4, marginBottom: 0 }} type="secondary">
              积分 TOP：{team?.top_points.map((t) => `${t.name}(${t.value})`).join('、')}
            </Typography.Paragraph>
          )}
        </Card>
      </Col>
      <Col span={24}>
        <Card
          title={
            <span>
              <AlertOutlined /> 告警
            </span>
          }
        >
          <List
            dataSource={alerts}
            locale={{ emptyText: '暂无告警' }}
            renderItem={(item) => (
              <List.Item>
                <Tag color={ALERT_COLORS[item.type] ?? 'default'}>{item.type}</Tag>
                {item.link ? <Link to={item.link}>{item.title}</Link> : item.title}
              </List.Item>
            )}
          />
        </Card>
      </Col>
    </Row>
  );
}
