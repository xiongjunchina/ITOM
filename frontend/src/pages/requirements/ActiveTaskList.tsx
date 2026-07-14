import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Button, Empty, Select, Space, Switch, Table, Tag, Tooltip, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ReloadOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';
import type { ActiveTaskRow, RequirementTaskStatus } from '../../api/types';
import { REQ_TASK_STATUSES, REQ_TASK_STATUS_COLORS } from '../../api/types';
import { QuadrantTag, ReqStatusBadge } from './shared';

/** 计划/实际工天展示：形如「计划5·实际3」，均空显示 - */
function effortText(
  plan: number | null,
  actual: number | null,
  t: (k: string, p?: Record<string, string | number>) => string,
): string {
  if (plan == null && actual == null) return '-';
  const parts: string[] = [];
  if (plan != null) parts.push(t('req.activeTask.planN', { n: plan }));
  if (actual != null) parts.push(t('req.activeTask.actualN', { n: actual }));
  return parts.join('·');
}

/** 实现任务清单：跨需求聚合排期/实现中(analyzing/implementing)的任务 */
export default function ActiveTaskList() {
  const t = useT();
  const et = useEnums();

  const [rows, setRows] = useState<ActiveTaskRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<RequirementTaskStatus | undefined>();
  const [mineOnly, setMineOnly] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get<ActiveTaskRow[]>('/requirements/tasks/active', {
        scope: mineOnly ? 'mine' : undefined,
        status: status || undefined,
      });
      setRows(data ?? []);
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, [mineOnly, status]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns: ColumnsType<ActiveTaskRow> = [
    {
      title: t('req.activeTask.col.name'),
      dataIndex: 'name',
      width: 200,
      ellipsis: true,
    },
    {
      title: t('req.activeTask.col.desc'),
      dataIndex: 'description',
      width: 220,
      ellipsis: true,
      render: (v: string | null) =>
        v ? (
          <Tooltip title={v}>
            <Typography.Text style={{ maxWidth: 200 }} ellipsis>
              {v}
            </Typography.Text>
          </Tooltip>
        ) : (
          '-'
        ),
    },
    {
      title: t('req.activeTask.col.owner'),
      dataIndex: 'assignee_name',
      width: 110,
      render: (v: string | null) => v || '-',
    },
    {
      title: t('req.activeTask.col.relReq'),
      key: 'req',
      width: 240,
      render: (_, r) => (
        <Link to={`/requirements/${r.requirement_id}`}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {r.requirement_code}
          </Typography.Text>
          <div>
            <Typography.Text ellipsis style={{ maxWidth: 200 }}>
              {r.requirement_title}
            </Typography.Text>
          </div>
        </Link>
      ),
    },
    {
      title: t('req.activeTask.col.reqStage'),
      key: 'reqStage',
      width: 110,
      render: (_, r) => <ReqStatusBadge status={r.requirement_status} name={r.requirement_status_name} />,
    },
    {
      title: t('req.activeTask.col.quadrant'),
      dataIndex: 'quadrant',
      width: 130,
      render: (v: string | null) => <QuadrantTag value={v} />,
    },
    {
      title: t('req.activeTask.col.planDate'),
      dataIndex: 'plan_date',
      width: 110,
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (v: string | null) => v || '-',
    },
    {
      title: t('req.activeTask.col.effort'),
      key: 'effort',
      width: 130,
      render: (_, r) => effortText(r.plan_effort, r.actual_effort, t),
    },
    {
      title: t('req.activeTask.col.progress'),
      dataIndex: 'status',
      width: 100,
      render: (v: RequirementTaskStatus) => <Tag color={REQ_TASK_STATUS_COLORS[v]}>{et.reqTaskStatus(v)}</Tag>,
    },
  ];

  return (
    <div>
      <Space wrap style={{ marginBottom: 16 }}>
        <Select
          placeholder={t('req.filter.taskStatus')}
          allowClear
          style={{ width: 140 }}
          value={status}
          onChange={(v) => setStatus(v)}
          options={REQ_TASK_STATUSES.map((s) => ({ value: s, label: et.reqTaskStatus(s) }))}
        />
        <span>
          {t('req.filter.onlyMine')} <Switch checked={mineOnly} onChange={(v) => setMineOnly(v)} />
        </span>
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>
          {t('common.refresh')}
        </Button>
      </Space>

      <Table<ActiveTaskRow>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={rows}
        sticky
        scroll={{ x: 1350 }}
        pagination={false}
        locale={{
          emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('req.activeTask.empty')} />,
        }}
      />
    </div>
  );
}
