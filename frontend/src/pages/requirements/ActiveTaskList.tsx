import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Button,
  DatePicker,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';
import type { Dayjs } from 'dayjs';
import type { ActiveTaskRow, Member, RequirementRow, RequirementTaskStatus } from '../../api/types';
import { useAuthStore, hasPermission } from '../../stores/auth';
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

  const user = useAuthStore((st) => st.user);
  const canEdit = user?.permissions ? hasPermission(user, 'requirements', 'edit') : true;

  const [rows, setRows] = useState<ActiveTaskRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<RequirementTaskStatus | undefined>();
  const [mineOnly, setMineOnly] = useState(false);

  // 登记任务（M16.2）：开发 leader 在本页直接给实现中的需求录任务清单
  const [addOpen, setAddOpen] = useState(false);
  const [addSaving, setAddSaving] = useState(false);
  const [addForm] = Form.useForm();
  const [reqOptions, setReqOptions] = useState<{ value: string; label: string }[]>([]);
  const [memberOptions, setMemberOptions] = useState<{ value: string; label: string }[]>([]);

  const openAdd = async () => {
    addForm.resetFields();
    setAddOpen(true);
    try {
      const [reqs, members] = await Promise.all([
        api.getList<RequirementRow>('/requirements', { status: 'implementing', page: 1, page_size: 200 }),
        api.getList<Member>('/members', { page: 1, page_size: 999 }),
      ]);
      setReqOptions(
        reqs.items
          .filter((r) => !r.is_example && !r.project_id)  // 转项目的需求由项目侧交付，不在此录任务
          .map((r) => ({ value: r.id, label: `${r.requirement_code} ${r.title}` })),
      );
      setMemberOptions(members.items.map((m) => ({ value: m.id, label: m.name })));
    } catch {
      // 已统一提示
    }
  };

  const submitAdd = async () => {
    const v = await addForm.validateFields();
    setAddSaving(true);
    try {
      await api.post(`/requirements/${v.requirement_id}/tasks`, {
        name: v.name,
        description: v.description || undefined,
        assignee: v.assignee,
        plan_date: v.plan_date ? (v.plan_date as Dayjs).format('YYYY-MM-DD') : undefined,
        plan_effort: v.plan_effort ?? undefined,
      });
      message.success(t('req.activeTask.added'));
      setAddOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setAddSaving(false);
    }
  };

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
      // M16：清单已按所属需求加权总分降序返回，列标题 Tooltip 说明排序依据
      title: (
        <Tooltip title={t('req.activeTask.sortHint')}>
          <span>{t('req.col.weightedTotal')} ↓</span>
        </Tooltip>
      ),
      dataIndex: 'weighted_total',
      width: 110,
      align: 'right',
      render: (v: number | null) => (v == null ? '-' : v.toFixed(1)),
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
        {canEdit && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => void openAdd()}>
            {t('req.activeTask.add')}
          </Button>
        )}
      </Space>

      <Modal
        title={t('req.activeTask.add')}
        open={addOpen}
        onOk={() => void submitAdd()}
        confirmLoading={addSaving}
        onCancel={() => setAddOpen(false)}
        destroyOnClose
        width={560}
      >
        <Form form={addForm} layout="vertical" preserve={false}>
          <Form.Item
            name="requirement_id"
            label={t('req.activeTask.pickReq')}
            rules={[{ required: true, message: t('req.activeTask.pickReqRequired') }]}
            extra={t('req.activeTask.pickReqHint')}
          >
            <Select showSearch optionFilterProp="label" options={reqOptions} placeholder={t('req.activeTask.pickReq')} />
          </Form.Item>
          <Form.Item name="name" label={t('req.activeTask.col.name')} rules={[{ required: true, message: t('req.activeTask.nameRequired') }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="description" label={t('req.task.desc')}>
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
          <Space size={16} wrap>
            <Form.Item name="assignee" label={t('req.activeTask.col.owner')} rules={[{ required: true, message: t('req.selectMember') }]}>
              <Select showSearch optionFilterProp="label" style={{ width: 180 }} options={memberOptions} />
            </Form.Item>
            <Form.Item name="plan_date" label={t('req.activeTask.col.planDate')}>
              <DatePicker />
            </Form.Item>
            <Form.Item name="plan_effort" label={t('req.task.planEffort')}>
              <InputNumber min={0} precision={1} style={{ width: 110 }} />
            </Form.Item>
          </Space>
        </Form>
      </Modal>

      <Table<ActiveTaskRow>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={rows}
        sticky
        scroll={{ x: 1460 }}
        pagination={false}
        locale={{
          emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('req.activeTask.empty')} />,
        }}
      />
    </div>
  );
}
