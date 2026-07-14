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
import { useT } from '../../i18n';
import type { SlaDashboard, SlaPolicy, TicketPriority } from '../../api/types';
import { PRIORITY_COLORS } from '../../api/types';

const PRIORITIES: TicketPriority[] = ['P1', 'P2', 'P3', 'P4'];

type WarningTicket = SlaDashboard['warning_tickets'][number];

export default function SlaBoard() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const isAdmin = hasAnyRole(user, ['admin']);
  const t = useT();

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
      message.success(t('itsm.sla.policySaved'));
      setDirty(false);
      void loadBoard();
    } catch {
      // 已统一提示
    } finally {
      setPolicySaving(false);
    }
  };

  const warningColumns: ColumnsType<WarningTicket> = [
    { title: t('itsm.f.code'), dataIndex: 'ticket_code', width: 140, onCell: () => ({ className: 'cell-nowrap' }) },
    { title: t('itsm.f.title'), dataIndex: 'title', ellipsis: true },
    {
      title: t('itsm.f.priority'),
      dataIndex: 'priority',
      width: 90,
      render: (v: TicketPriority) => <Tag color={PRIORITY_COLORS[v]}>{v}</Tag>,
    },
    { title: t('common.status'), dataIndex: 'status', width: 110 },
    {
      title: t('itsm.f.submittedAt'),
      dataIndex: 'submitted_at',
      width: 150,
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'),
    },
    {
      title: t('itsm.sla.resolutionTargetH'),
      dataIndex: 'sla_resolution_hours',
      width: 130,
      render: (v: number | null) => v ?? '-',
    },
  ];

  const policyColumns: ColumnsType<SlaPolicy> = [
    {
      title: t('itsm.f.priority'),
      dataIndex: 'priority',
      width: 100,
      render: (v: TicketPriority) => <Tag color={PRIORITY_COLORS[v]}>{v}</Tag>,
    },
    {
      title: t('itsm.sla.responseLimitMin'),
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
      title: t('itsm.sla.resolutionLimitH'),
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
      title: t('itsm.sla.enabled'),
      dataIndex: 'active',
      width: 100,
      render: (v: boolean, r) =>
        isAdmin ? (
          <Switch checked={v} onChange={(val) => updatePolicy(r.priority, { active: val })} />
        ) : (
          <Tag color={v ? 'green' : 'default'}>{v ? t('itsm.sla.enabled') : t('itsm.sla.disabled')}</Tag>
        ),
    },
  ];

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title={
          <span>
            {t('itsm.sla.monthlyRate')}
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
                        {t('itsm.sla.rate')}
                      </Space>
                    }
                    value={stat?.rate ?? '-'}
                    suffix={stat?.rate != null ? '%' : undefined}
                    valueStyle={
                      stat?.rate != null && stat.rate < 90 ? { color: '#cf1322' } : undefined
                    }
                  />
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {t('itsm.sla.resolvedMet', { resolved: stat?.resolved ?? 0, met: stat?.met ?? 0 })}
                  </Typography.Text>
                </Card>
              </Col>
            );
          })}
        </Row>
      </Card>

      <Card title={t('itsm.sla.warnCard')}>
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
          locale={{ emptyText: t('itsm.sla.noWarn') }}
        />
      </Card>

      <Card
        title={t('itsm.sla.policyCard')}
        extra={
          isAdmin && (
            <Button
              type="primary"
              icon={<SaveOutlined />}
              disabled={!dirty}
              loading={policySaving}
              onClick={() => void savePolicies()}
            >
              {t('itsm.sla.savePolicy')}
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
