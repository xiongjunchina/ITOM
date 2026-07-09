import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Badge,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Modal,
  Rate,
  Select,
  Space,
  Spin,
  Steps,
  Tag,
  Typography,
  message,
} from 'antd';
import { ArrowLeftOutlined, EditOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from '../../api/client';
import { useAuthStore } from '../../stores/auth';
import type {
  AllowedTransition,
  MasterDataItem,
  Member,
  ProcessStep,
  TicketDetail as TicketDetailData,
  TicketType,
} from '../../api/types';
import { PRIORITY_COLORS, TICKET_TYPE_COLORS, TICKET_TYPE_LABELS } from '../../api/types';

const fmt = (v?: string | null) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-');

function statusBadge(status: string): 'default' | 'success' | 'error' | 'warning' | 'processing' {
  if (status === 'closed' || status === 'cancelled') return 'default';
  if (status === 'resolved' || status === 'approved') return 'success';
  if (status === 'rejected') return 'error';
  if (status === 'paused' || status === 'pending_approval') return 'warning';
  return 'processing';
}

function stepStatus(s: ProcessStep): 'finish' | 'process' | 'wait' {
  if (s.task_status === '已完成') return 'finish';
  if (s.task_status === '待处理') return 'process';
  return 'wait';
}

export default function TicketDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);

  const [detail, setDetail] = useState<TicketDetailData | null>(null);
  const [loading, setLoading] = useState(true);

  // 状态流转 Modal
  const [transition, setTransition] = useState<AllowedTransition | null>(null);
  const [transForm] = Form.useForm();
  const [transSaving, setTransSaving] = useState(false);
  const [closureCodes, setClosureCodes] = useState<MasterDataItem[]>([]);

  // 改派
  const [reassignOpen, setReassignOpen] = useState(false);
  const [reassignTo, setReassignTo] = useState<string | undefined>();
  const [reassignSaving, setReassignSaving] = useState(false);
  const [members, setMembers] = useState<Member[]>([]);

  // 完成流程步骤
  const [completingTask, setCompletingTask] = useState<ProcessStep | null>(null);
  const [taskComment, setTaskComment] = useState('');
  const [taskSaving, setTaskSaving] = useState(false);

  // 满意度
  const [rating, setRating] = useState(0);
  const [ratingSaving, setRatingSaving] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const data = await api.get<TicketDetailData>(`/tickets/${id}`);
      setDetail(data);
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const loadMembers = () => {
    if (members.length === 0) {
      api
        .getList<Member>('/members', { page: 1, page_size: 999 })
        .then((res) => setMembers(res.items))
        .catch(() => undefined);
    }
  };

  const openTransition = (t: AllowedTransition) => {
    const needsForm = t.to === 'resolved' || t.to === 'closed' || t.to === 'approved' || t.to === 'rejected';
    if (!needsForm) {
      Modal.confirm({
        title: `确认执行「${t.to_name}」？`,
        onOk: async () => {
          await api.post(`/tickets/${id}/transition`, { to: t.to, fields: {} });
          message.success('操作成功');
          void load();
        },
      });
      return;
    }
    if (t.to === 'closed' && closureCodes.length === 0) {
      api
        .getList<MasterDataItem>('/admin/master-data', {
          category: 'closure_code',
          page: 1,
          page_size: 999,
        })
        .then((res) => setClosureCodes(res.items.filter((c) => c.active !== false)))
        .catch(() => undefined);
    }
    transForm.resetFields();
    setTransition(t);
  };

  const submitTransition = async () => {
    if (!transition) return;
    const values = await transForm.validateFields();
    const fields: Record<string, unknown> = {};
    if (transition.to === 'resolved') {
      fields.solution = values.solution;
      if (values.root_cause) fields.root_cause = values.root_cause;
    } else if (transition.to === 'closed') {
      fields.closure_code = values.closure_code;
    } else if (transition.to === 'approved' || transition.to === 'rejected') {
      if (values.approval_comment) fields.approval_comment = values.approval_comment;
    }
    setTransSaving(true);
    try {
      await api.post(`/tickets/${id}/transition`, { to: transition.to, fields });
      message.success('操作成功');
      setTransition(null);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setTransSaving(false);
    }
  };

  const submitReassign = async () => {
    if (reassignTo == null) {
      message.warning('请选择受理人');
      return;
    }
    setReassignSaving(true);
    try {
      await api.patch(`/tickets/${id}`, { assignee: reassignTo });
      message.success('受理人已更新');
      setReassignOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setReassignSaving(false);
    }
  };

  const submitTaskComplete = async () => {
    if (!completingTask?.task_id) return;
    setTaskSaving(true);
    try {
      await api.post(`/process-tasks/${completingTask.task_id}/complete`, { comment: taskComment });
      message.success('步骤已完成');
      setCompletingTask(null);
      setTaskComment('');
      void load();
    } catch {
      // 已统一提示
    } finally {
      setTaskSaving(false);
    }
  };

  const submitRating = async () => {
    if (!rating) {
      message.warning('请先选择评分');
      return;
    }
    setRatingSaving(true);
    try {
      await api.post(`/tickets/${id}/satisfaction`, { score: rating });
      message.success('感谢您的评价');
      void load();
    } catch {
      // 已统一提示
    } finally {
      setRatingSaving(false);
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" />
      </div>
    );
  }
  if (!detail) {
    return (
      <Card>
        <Typography.Text type="secondary">工单不存在或无权查看</Typography.Text>
      </Card>
    );
  }

  const isChange = detail.ticket_type === 'change';
  const isSubmitter = !!user && !!detail.submitter && detail.submitter === user.id;
  const canRate = detail.status === 'closed' && isSubmitter && detail.satisfaction == null;
  const process = detail.process;

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card>
        <Space style={{ width: '100%', justifyContent: 'space-between', flexWrap: 'wrap' }}>
          <Space size="middle" wrap>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/itsm/tickets')}>
              返回
            </Button>
            <Typography.Title level={4} style={{ margin: 0 }}>
              {detail.ticket_code} · {detail.title}
            </Typography.Title>
            <Badge status={statusBadge(detail.status)} text={detail.status_name || detail.status} />
            <Tag color={PRIORITY_COLORS[detail.priority]}>{detail.priority}</Tag>
            <Tag color={TICKET_TYPE_COLORS[detail.ticket_type as TicketType]}>
              {TICKET_TYPE_LABELS[detail.ticket_type as TicketType] ?? detail.ticket_type}
            </Tag>
          </Space>
          <Space wrap>
            {(detail.allowed_transitions ?? []).map((t) => (
              <Button
                key={t.to}
                type={t.to === 'rejected' ? 'default' : 'primary'}
                danger={t.to === 'rejected'}
                onClick={() => openTransition(t)}
              >
                {t.to_name}
              </Button>
            ))}
          </Space>
        </Space>
      </Card>

      {process && process.steps?.length > 0 && (
        <Card title={`流程：${process.definition_name}`} size="small">
          <Steps
            size="small"
            current={Math.max(
              process.steps.findIndex((s) => s.task_status === '待处理'),
              0,
            )}
            items={process.steps.map((s) => ({
              title: s.name,
              status: stepStatus(s),
              description: (
                <Space direction="vertical" size={0}>
                  <span>
                    {s.assignee_name ?? s.default_role ?? '-'}
                    {s.autonomy_level ? ` · ${s.autonomy_level}` : ''}
                  </span>
                  {s.completed_at && <span>{fmt(s.completed_at)}</span>}
                  {s.task_status === '待处理' && s.task_id != null && (
                    <Button
                      size="small"
                      type="link"
                      style={{ padding: 0 }}
                      onClick={() => {
                        setTaskComment('');
                        setCompletingTask(s);
                      }}
                    >
                      完成此步骤
                    </Button>
                  )}
                </Space>
              ),
            }))}
          />
        </Card>
      )}

      <Card title="基本信息" size="small">
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="服务项">{detail.service_item_name ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="服务线">{detail.service_line ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="提交人">
            {detail.submitter_name ?? '-'}
            {detail.submitter_dept ? `（${detail.submitter_dept}）` : ''}
          </Descriptions.Item>
          <Descriptions.Item label="受理人">
            <Space>
              {detail.assignee_name ?? '-'}
              <Button
                type="link"
                size="small"
                icon={<EditOutlined />}
                onClick={() => {
                  loadMembers();
                  setReassignTo(detail.assignee ?? undefined);
                  setReassignOpen(true);
                }}
              >
                改派
              </Button>
            </Space>
          </Descriptions.Item>
          <Descriptions.Item label="提交时间">{fmt(detail.submitted_at)}</Descriptions.Item>
          <Descriptions.Item label="首次响应">{fmt(detail.first_response_at)}</Descriptions.Item>
          <Descriptions.Item label="解决时间">{fmt(detail.resolved_at)}</Descriptions.Item>
          <Descriptions.Item label="关闭时间">{fmt(detail.closed_at)}</Descriptions.Item>
          <Descriptions.Item label="SLA 响应目标">
            {detail.sla_response_min != null ? `${detail.sla_response_min} 分钟` : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="实际响应">
            {detail.actual_response_min != null ? (
              <Space>
                {detail.actual_response_min} 分钟
                {detail.sla_response_met === true && <Tag color="green">达成</Tag>}
                {detail.sla_response_met === false && <Tag color="red">超时</Tag>}
              </Space>
            ) : (
              '-'
            )}
          </Descriptions.Item>
          <Descriptions.Item label="SLA 解决目标">
            {detail.sla_resolution_hours != null ? `${detail.sla_resolution_hours} 小时` : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="实际解决">
            {detail.actual_resolution_hours != null ? (
              <Space>
                {detail.actual_resolution_hours} 小时
                {detail.sla_resolution_met === true && <Tag color="green">达成</Tag>}
                {detail.sla_resolution_met === false && <Tag color="red">超时</Tag>}
                {detail.sla_resolution_met == null && detail.sla_warned && <Tag color="orange">临期</Tag>}
              </Space>
            ) : detail.sla_warned ? (
              <Tag color="orange">临期 ⚠</Tag>
            ) : (
              '-'
            )}
          </Descriptions.Item>
          <Descriptions.Item label="重开次数">{detail.reopen_count ?? 0}</Descriptions.Item>
          <Descriptions.Item label="一次解决">
            {detail.first_time_fix == null ? '-' : detail.first_time_fix ? '是' : '否'}
          </Descriptions.Item>
          <Descriptions.Item label="暂停时长">
            {detail.paused_minutes != null ? `${detail.paused_minutes} 分钟` : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="满意度">
            {detail.satisfaction != null ? <Rate disabled value={detail.satisfaction} /> : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="描述" span={2}>
            <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
              {detail.description || '-'}
            </Typography.Paragraph>
          </Descriptions.Item>
          {detail.remarks && (
            <Descriptions.Item label="备注" span={2}>
              {detail.remarks}
            </Descriptions.Item>
          )}
          {detail.closure_code && (
            <Descriptions.Item label="关闭代码" span={2}>
              {detail.closure_code}
            </Descriptions.Item>
          )}
        </Descriptions>
      </Card>

      {isChange && (
        <Card title="变更信息" size="small">
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="变更类型">{detail.change_type ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="风险等级">{detail.risk_level ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="计划开始">{fmt(detail.planned_start_at)}</Descriptions.Item>
            <Descriptions.Item label="计划结束">{fmt(detail.planned_end_at)}</Descriptions.Item>
            <Descriptions.Item label="变更原因" span={2}>
              {detail.change_reason ?? '-'}
            </Descriptions.Item>
            <Descriptions.Item label="回退方案" span={2}>
              {detail.rollback_plan ?? '-'}
            </Descriptions.Item>
            <Descriptions.Item label="实施方案" span={2}>
              {detail.implementation_plan ?? '-'}
            </Descriptions.Item>
            <Descriptions.Item label="审批时间">{fmt(detail.approved_at)}</Descriptions.Item>
            <Descriptions.Item label="审批意见">{detail.approval_comment ?? '-'}</Descriptions.Item>
          </Descriptions>
        </Card>
      )}

      {(detail.solution || detail.root_cause) && (
        <Card title="解决方案 / 根因" size="small">
          <Descriptions column={1} size="small" bordered>
            {detail.solution && (
              <Descriptions.Item label="解决方案">
                <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                  {detail.solution}
                </Typography.Paragraph>
              </Descriptions.Item>
            )}
            {detail.root_cause && (
              <Descriptions.Item label="根因">
                <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                  {detail.root_cause}
                </Typography.Paragraph>
              </Descriptions.Item>
            )}
          </Descriptions>
        </Card>
      )}

      {canRate && (
        <Card title="满意度评价" size="small">
          <Space>
            <Rate value={rating} onChange={setRating} />
            <Button type="primary" loading={ratingSaving} onClick={() => void submitRating()}>
              提交评价
            </Button>
          </Space>
        </Card>
      )}

      {/* 状态流转 Modal */}
      <Modal
        title={transition ? `${transition.to_name}` : ''}
        open={!!transition}
        onOk={() => void submitTransition()}
        confirmLoading={transSaving}
        onCancel={() => setTransition(null)}
        destroyOnClose
      >
        <Form form={transForm} layout="vertical" preserve={false}>
          {transition?.to === 'resolved' && (
            <>
              <Form.Item
                name="solution"
                label="解决方案"
                rules={[{ required: true, message: '请填写解决方案' }]}
              >
                <Input.TextArea rows={4} maxLength={2000} />
              </Form.Item>
              <Form.Item name="root_cause" label="根因（可选）">
                <Input.TextArea rows={3} maxLength={2000} />
              </Form.Item>
            </>
          )}
          {transition?.to === 'closed' && (
            <Form.Item
              name="closure_code"
              label="关闭代码"
              rules={[{ required: true, message: '请选择关闭代码' }]}
            >
              <Select
                placeholder="选择关闭代码"
                options={closureCodes.map((c) => ({ value: c.code, label: c.name }))}
              />
            </Form.Item>
          )}
          {(transition?.to === 'approved' || transition?.to === 'rejected') && (
            <Form.Item name="approval_comment" label="审批意见">
              <Input.TextArea rows={3} maxLength={1000} />
            </Form.Item>
          )}
        </Form>
      </Modal>

      {/* 改派 Modal */}
      <Modal
        title="改派受理人"
        open={reassignOpen}
        onOk={() => void submitReassign()}
        confirmLoading={reassignSaving}
        onCancel={() => setReassignOpen(false)}
        destroyOnClose
      >
        <Select
          style={{ width: '100%' }}
          showSearch
          optionFilterProp="label"
          placeholder="选择新的受理人"
          value={reassignTo}
          onChange={setReassignTo}
          options={members.map((m) => ({
            value: m.id,
            label: m.dept ? `${m.name}（${m.dept}）` : m.name,
          }))}
        />
      </Modal>

      {/* 完成流程步骤 Modal */}
      <Modal
        title={completingTask ? `完成步骤：${completingTask.name}` : ''}
        open={!!completingTask}
        onOk={() => void submitTaskComplete()}
        confirmLoading={taskSaving}
        onCancel={() => setCompletingTask(null)}
        destroyOnClose
      >
        <Input.TextArea
          rows={3}
          maxLength={500}
          placeholder="处理说明（可选）"
          value={taskComment}
          onChange={(e) => setTaskComment(e.target.value)}
        />
      </Modal>
    </Space>
  );
}
