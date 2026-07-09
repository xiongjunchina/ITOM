import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Button,
  Card,
  Col,
  InputNumber,
  Row,
  Space,
  Statistic,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { SaveOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from '../../api/client';
import { useAuthStore, hasAnyRole } from '../../stores/auth';
import type { SlaDashboard, SlaPolicy, TicketPriority } from '../../api/types';
import { PRIORITY_COLORS } from '../../api/types';

const PRIORITIES: TicketPriority[] = ['P1', 'P2', 'P3', 'P4'];

type WarningTicket = SlaDashboard['warning_tickets'][number];

export default function SlaBoard() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const isAdmin = hasAnyRole(user, ['admin']);

  const [board, setBoard] = useState<SlaDashboard | null>(null);
  const [boardLoading, setBoardLoading] = useState(true);

  const [policies, setPolicies] = useState<SlaPolicy[]>([]);
  const [policyLoading, setPolicyLoading] = useState(false);
  const [policySaving, setPolicySaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  const loadBoard = useCallback(async () => {
    setBoardLoading(true);
    try {
      const data = await api.get<SlaDashboard>('/sla/dashboard');
      setBoard(data);
    } catch {
      // 已统一提示
    } finally {
      setBoardLoading(false);
    }
  }, []);

  const loadPolicies = useCallback(async () => {
    setPolicyLoading(true);
    try {
      const data = await api.get<SlaPolicy[]>('/admin/sla-policies');
      setPolicies(data ?? []);
      setDirty(false);
    } catch {
      // 已统一提示
    } finally {
      setPolicyLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadBoard();
    void loadPolicies();
  }, [loadBoard, loadPolicies]);

  const updatePolicy = (priority: TicketPriority, patch: Partial<SlaPolicy>) => {
    setPolicies((prev) => prev.map((p) => (p.priority === priority ? { ...p, ...patch } : p)));
    setDirty(true);
  };

  const savePolicies = async () => {
    setPolicySaving(true);
    try {
      await api.put(
        '/admin/sla-policies',
        policies.map((p) => ({
          priority: p.priority,
          response_minutes: p.response_minutes,
          resolution_hours: p.resolution_hours,
          active: p.active,
        })),
      );
      message.success('SLA 策略已保存');
      setDirty(false);
      void loadBoard();
    } catch {
      // 已统一提示
    } finally {
      setPolicySaving(false);
    }
  };

  const warningColumns: ColumnsType<WarningTicket> = [
    { title: '编号', dataIndex: 'ticket_code', width: 140 },
    { title: '标题', dataIndex: 'title', ellipsis: true },
    {
      title: '优先级',
      dataIndex: 'priority',
      width: 90,
      render: (v: TicketPriority) => <Tag color={PRIORITY_COLORS[v]}>{v}</Tag>,
    },
    { title: '状态', dataIndex: 'status', width: 110 },
    {
      title: '提交时间',
      dataIndex: 'submitted_at',
      width: 150,
      render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'),
    },
    {
      title: 'SLA 解决目标(h)',
      dataIndex: 'sla_resolution_hours',
      width: 130,
      render: (v: number | null) => v ?? '-',
    },
  ];

  const policyColumns: ColumnsType<SlaPolicy> = [
    {
      title: '优先级',
      dataIndex: 'priority',
      width: 100,
      render: (v: TicketPriority) => <Tag color={PRIORITY_COLORS[v]}>{v}</Tag>,
    },
    {
      title: '响应时限(分钟)',
      dataIndex: 'response_minutes',
      width: 180,
      render: (v: number, r) =>
        isAdmin ? (
          <InputNumber
            min={1}
            value={v}
            onChange={(val) => updatePolicy(r.priority, { response_minutes: val ?? v })}
          />
        ) : (
          v
        ),
    },
    {
      title: '解决时限(小时)',
      dataIndex: 'resolution_hours',
      width: 180,
      render: (v: number, r) =>
        isAdmin ? (
          <InputNumber
            min={1}
            value={v}
            onChange={(val) => updatePolicy(r.priority, { resolution_hours: val ?? v })}
          />
        ) : (
          v
        ),
    },
    {
      title: '启用',
      dataIndex: 'active',
      width: 100,
      render: (v: boolean, r) =>
        isAdmin ? (
          <Switch checked={v} onChange={(val) => updatePolicy(r.priority, { active: val })} />
        ) : (
          <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '停用'}</Tag>
        ),
    },
  ];

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title={
          <span>
            本月 SLA 达成率
            {board?.month && (
              <Typography.Text type="secondary" style={{ marginLeft: 8, fontWeight: 'normal' }}>
                （{board.month}）
              </Typography.Text>
            )}
          </span>
        }
        loading={boardLoading}
      >
        <Row gutter={16}>
          {PRIORITIES.map((p) => {
            const stat = board?.by_priority?.[p];
            return (
              <Col xs={12} md={6} key={p}>
                <Card size="small">
                  <Statistic
                    title={
                      <Space>
                        <Tag color={PRIORITY_COLORS[p]}>{p}</Tag>
                        达成率
                      </Space>
                    }
                    value={stat?.rate ?? '-'}
                    suffix={stat?.rate != null ? '%' : undefined}
                    valueStyle={
                      stat?.rate != null && stat.rate < 90 ? { color: '#cf1322' } : undefined
                    }
                  />
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    已解决 {stat?.resolved ?? 0} · 达成 {stat?.met ?? 0}
                  </Typography.Text>
                </Card>
              </Col>
            );
          })}
        </Row>
      </Card>

      <Card title="临期 / 超时工单">
        <Table<WarningTicket>
          rowKey="id"
          loading={boardLoading}
          columns={warningColumns}
          dataSource={board?.warning_tickets ?? []}
          pagination={false}
          scroll={{ x: 800 }}
          onRow={(record) => ({
            onClick: () => navigate(`/itsm/tickets/${record.id}`),
            style: { cursor: 'pointer' },
          })}
          locale={{ emptyText: '暂无临期或超时工单' }}
        />
      </Card>

      <Card
        title="SLA 策略"
        extra={
          isAdmin && (
            <Button
              type="primary"
              icon={<SaveOutlined />}
              disabled={!dirty}
              loading={policySaving}
              onClick={() => void savePolicies()}
            >
              保存策略
            </Button>
          )
        }
      >
        <Table<SlaPolicy>
          rowKey="priority"
          loading={policyLoading}
          columns={policyColumns}
          dataSource={policies}
          pagination={false}
        />
      </Card>
    </Space>
  );
}
