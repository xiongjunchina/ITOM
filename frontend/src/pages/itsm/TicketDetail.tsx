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
import { ExampleAlert } from '../../components/ExampleTag';
import ProcessActionButtons from '../../components/ProcessActionButtons';
import { canHandleTask, hasPermission, useAuthStore } from '../../stores/auth';
import { useRoleOptions } from '../../utils/roleOptions';
import { useGoBack } from '../../utils/nav';
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';
import type {
  AllowedTransition,
  MasterDataItem,
  Member,
  ProcessStep,
  TicketDetail as TicketDetailData,
  TicketType,
} from '../../api/types';
import { PRIORITY_COLORS, TICKET_TYPE_COLORS } from '../../api/types';

const fmt = (v?: string | null) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-');

/** 工单类型 → 列表页（返回兜底：通知/直链打开无站内历史时使用） */
const TYPE_LIST_PATH: Record<TicketType, string> = {
  service_request: '/itsm/tickets',
  incident: '/itsm/incidents',
  change: '/itsm/changes',
};

function statusBadge(status: string): 'default' | 'success' | 'error' | 'warning' | 'processing' {
  if (status === 'closed' || status === 'cancelled') return 'default';
  if (status === 'resolved' || status === 'approved') return 'success';
  if (status === 'rejected') return 'error';
  if (status === 'paused' || status === 'pending_approval') return 'warning';
  return 'processing';
}

function stepStatus(s: ProcessStep): 'finish' | 'process' | 'wait' | 'error' {
  if (s.task_status === '已驳回') return 'error';
  if (s.task_status === '已完成') return 'finish';
  if (s.task_status === '待处理') return 'process';
  return 'wait';
}

export default function TicketDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const goBack = useGoBack();
  const user = useAuthStore((s) => s.user);
  const t = useT();
  const et = useEnums();

  /** 角色/组 code → 中文名（流程条处理人与知会人展示） */
  const { roleLabel } = useRoleOptions();

  const [detail, setDetail] = useState<TicketDetailData | null>(null);
  const [loading, setLoading] = useState(true);

  // 状态流转 Modal
  const [transition, setTransition] = useState<AllowedTransition | null>(null);
  const [transForm] = Form.useForm();
  const [transSaving, setTransSaving] = useState(false);
  const [closureCodes, setClosureCodes] = useState<MasterDataItem[]>([]);

  // M28 主动关闭（登记人/admin）
  const [closeOpen, setCloseOpen] = useState(false);
  const [closeReason, setCloseReason] = useState('');
  const [closeSaving, setCloseSaving] = useState(false);
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
  const [ratingTags, setRatingTags] = useState<string[]>([]);
  const [ratingComment, setRatingComment] = useState('');
  const [ratingSaving, setRatingSaving] = useState(false);

  // M3：升级为问题 / 沉淀为知识
  const [escalating, setEscalating] = useState(false);
  const [toKnowledgeSaving, setToKnowledgeSaving] = useState(false);

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
        .getList<Member>('/members', { page: 1, page_size: 2000, scope: 'it' })
        .then((res) => setMembers(res.items))
        .catch(() => undefined);
    }
  };

  const openTransition = (tr: AllowedTransition) => {
    const needsForm = tr.to === 'resolved' || tr.to === 'closed' || tr.to === 'approved' || tr.to === 'rejected';
    if (!needsForm) {
      Modal.confirm({
        title: t('itsm.confirmAction', { name: tr.to_name }),
        onOk: async () => {
          await api.post(`/tickets/${id}/transition`, { to: tr.to, fields: {} });
          message.success(t('itsm.actionOk'));
          void load();
        },
      });
      return;
    }
    if (tr.to === 'closed' && closureCodes.length === 0) {
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
    setTransition(tr);
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
      message.success(t('itsm.actionOk'));
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
      message.warning(t('itsm.ticket.selectAssignee'));
      return;
    }
    setReassignSaving(true);
    try {
      await api.patch(`/tickets/${id}`, { assignee: reassignTo });
      message.success(t('itsm.ticket.assigneeUpdated'));
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
      message.success(t('itsm.stepDone'));
      setCompletingTask(null);
      setTaskComment('');
      void load();
    } catch {
      // 已统一提示
    } finally {
      setTaskSaving(false);
    }
  };

  const escalateProblem = async () => {
    setEscalating(true);
    try {
      const res = await api.post<{ problem_id: string; problem_code: string }>(
        `/tickets/${id}/escalate-problem`,
      );
      message.success(t('itsm.ticket.escalated', { code: res.problem_code }));
      navigate(`/itsm/problems/${res.problem_id}`);
    } catch {
      // 已统一提示（含 ALREADY_ESCALATED）
    } finally {
      setEscalating(false);
    }
  };

  const toKnowledge = async () => {
    setToKnowledgeSaving(true);
    try {
      const res = await api.post<{ article_id: string; article_code: string }>(
        `/tickets/${id}/to-knowledge`,
      );
      message.success(t('itsm.ticket.toKnowledgeOk', { code: res.article_code ?? '' }));
      navigate(`/itsm/knowledge/${res.article_id}`);
    } catch {
      // 已统一提示
    } finally {
      setToKnowledgeSaving(false);
    }
  };

  const submitRating = async () => {
    if (!rating) {
      message.warning(t('itsm.ticket.selectRating'));
      return;
    }
    setRatingSaving(true);
    try {
      await api.post(`/tickets/${id}/satisfaction`, {
        score: rating,
        tags: ratingTags,
        comment: ratingComment,
      });
      message.success(t('itsm.ticket.thanksRating'));
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
        <Typography.Text type="secondary">{t('itsm.ticket.notFound')}</Typography.Text>
      </Card>
    );
  }

  /** 示例数据只读：隐藏改派/升级/沉淀/满意度等残余写入口（allowed_transitions 后端已置空） */
  const isExample = detail.is_example === true;
  const isChange = detail.ticket_type === 'change';
  const isSubmitter = !!user && !!detail.submitter && detail.submitter === user.id;
  const canRate = !isExample && detail.status === 'closed' && isSubmitter && detail.satisfaction == null;
  const process = detail.process;
  const currentProcessStep = process?.steps?.find((s) => s.seq === process.current_step_seq);
  // M3：非 requester（拥有任一内部角色）可升级为问题
  const isStaff = !!user && user.roles.some((r) => r !== 'requester');
  const canEscalate = !isExample && isStaff && detail.status !== 'new' && detail.status !== 'closed';
  const canToKnowledge =
    !isExample && (detail.status === 'resolved' || detail.status === 'closed') && hasPermission(user, 'knowledge', 'create');

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {isExample && <ExampleAlert />}
      <Card>
        <Space style={{ width: '100%', justifyContent: 'space-between', flexWrap: 'wrap' }}>
          <Space size="middle" wrap>
            <Button icon={<ArrowLeftOutlined />} onClick={() => goBack(TYPE_LIST_PATH[detail.ticket_type as TicketType] ?? '/itsm/tickets')}>
              {t('itsm.back')}
            </Button>
            <Typography.Title level={4} style={{ margin: 0 }}>
              {detail.ticket_code} · {detail.title}
            </Typography.Title>
            <Badge status={statusBadge(detail.status)} text={detail.status_name || detail.status} />
            <Tag color={PRIORITY_COLORS[detail.priority]}>{detail.priority}</Tag>
            <Tag color={TICKET_TYPE_COLORS[detail.ticket_type as TicketType]}>
              {et.ticketType(detail.ticket_type)}
            </Tag>
          </Space>
          <Space wrap>
            {canRate && (
              <div
                role="group"
                aria-label={t('itsm.ticket.ratingCard')}
                style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}
              >
                <Typography.Text strong>{t('itsm.ticket.ratingCard')}</Typography.Text>
                <Space direction="vertical" size={8} style={{ alignItems: 'flex-end' }}>
                  <Rate value={rating} onChange={setRating} />
                  <Select
                    mode="tags"
                    value={ratingTags}
                    onChange={(values) => setRatingTags(values.slice(0, 5))}
                    tokenSeparators={[',', '，']}
                    placeholder={t('itsm.ticket.ratingTagsPlaceholder')}
                    style={{ width: 300 }}
                    options={[
                      t('itsm.ticket.ratingTagResponsive'),
                      t('itsm.ticket.ratingTagProfessional'),
                      t('itsm.ticket.ratingTagClear'),
                    ].map((value) => ({ value, label: value }))}
                  />
                  <Input.TextArea
                    value={ratingComment}
                    onChange={(event) => setRatingComment(event.target.value)}
                    maxLength={500}
                    autoSize={{ minRows: 2, maxRows: 4 }}
                    placeholder={t('itsm.ticket.ratingCommentPlaceholder')}
                    style={{ width: 300 }}
                  />
                  <Button type="primary" loading={ratingSaving} onClick={() => void submitRating()}>
                    {t('itsm.ticket.submitRating')}
                  </Button>
                </Space>
              </div>
            )}
            <ProcessActionButtons
              step={currentProcessStep}
              disabled={isExample}
              onDone={() => void load()}
            />
            {canEscalate && (
              <Button loading={escalating} onClick={() => void escalateProblem()}>
                {t('itsm.ticket.escalate')}
              </Button>
            )}
            {canToKnowledge && (
              <Button loading={toKnowledgeSaving} onClick={() => void toKnowledge()}>
                {t('itsm.ticket.toKnowledge')}
              </Button>
            )}
            {detail.can_close && (
              <Button
                danger
                onClick={() => {
                  setCloseReason('');
                  setCloseOpen(true);
                }}
              >
                {t('itsm.ticket.closeTitle')}
              </Button>
            )}
            {(detail.allowed_transitions ?? []).map((tr) => (
              <Button
                key={tr.to}
                type={tr.to === 'rejected' ? 'default' : 'primary'}
                danger={tr.to === 'rejected'}
                onClick={() => openTransition(tr)}
              >
                {tr.to_name}
              </Button>
            ))}
          </Space>
        </Space>
      </Card>

      {process && process.steps?.length > 0 && (
        <Card title={t('itsm.processTitle', { name: process.definition_name })} size="small">
          <Steps
            size="small"
            current={Math.max(
              process.steps.findIndex((s) => s.task_status === '待处理'),
              0,
            )}
            items={process.steps.map((s) => ({
              title: (
                <Space size={4}>
                  <span>{s.name}</span>
                  {s.node_type === 'approval' && <Tag color="gold">{t('comp.flow.approval')}</Tag>}
                </Space>
              ),
              status: stepStatus(s),
              description: (
                <Space direction="vertical" size={0}>
                  <span>
                    {s.assignee_name ?? (s.default_role ? roleLabel(s.default_role) : '-')}
                    {s.autonomy_level ? ` · ${s.autonomy_level}` : ''}
                  </span>
                  {(s.cc_roles?.length ?? 0) > 0 && (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {t('itsm.ccPrefix')}{(s.cc_roles ?? []).map((k) => roleLabel(k)).join('、')}
                    </Typography.Text>
                  )}
                  {s.completed_at && <span>{fmt(s.completed_at)}</span>}
                  {s.task_status === '待处理' && s.task_id != null && !isExample && canHandleTask(user, s) && (
                    <Button
                      size="small"
                      type="link"
                      style={{ padding: 0 }}
                      onClick={() => {
                        setTaskComment('');
                        setCompletingTask(s);
                      }}
                    >
                      {t('itsm.completeStep')}
                    </Button>
                  )}
                </Space>
              ),
            }))}
          />
        </Card>
      )}

      <Card title={t('itsm.basicInfo')} size="small">
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label={t('itsm.f.serviceItem')}>{detail.service_item_name ?? '-'}</Descriptions.Item>
          <Descriptions.Item label={t('itsm.ticket.serviceLine')}>{detail.service_line ?? '-'}</Descriptions.Item>
          <Descriptions.Item label={t('itsm.f.submitter')}>
            {detail.submitter_name ?? '-'}
            {detail.submitter_dept ? `（${detail.submitter_dept}）` : ''}
          </Descriptions.Item>
          <Descriptions.Item label={t('itsm.f.assignee')}>
            <Space>
              {detail.assignee_name ?? '-'}
              {!isExample && detail.can_edit !== false && (
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
                  {t('itsm.ticket.reassign')}
                </Button>
              )}
            </Space>
          </Descriptions.Item>
          <Descriptions.Item label={t('itsm.f.submittedAt')} contentStyle={{ whiteSpace: 'nowrap' }}>{fmt(detail.submitted_at)}</Descriptions.Item>
          <Descriptions.Item label={t('itsm.ticket.firstResponse')} contentStyle={{ whiteSpace: 'nowrap' }}>{fmt(detail.first_response_at)}</Descriptions.Item>
          <Descriptions.Item label={t('itsm.ticket.acceptedAt')} contentStyle={{ whiteSpace: 'nowrap' }}>{fmt(detail.accepted_at)}</Descriptions.Item>
          <Descriptions.Item label={t('itsm.ticket.resolvedAt')} contentStyle={{ whiteSpace: 'nowrap' }}>{fmt(detail.resolved_at)}</Descriptions.Item>
          <Descriptions.Item label={t('itsm.ticket.confirmationDueAt')} contentStyle={{ whiteSpace: 'nowrap' }}>{fmt(detail.confirmation_due_at)}</Descriptions.Item>
          <Descriptions.Item label={t('itsm.ticket.closedAt')} contentStyle={{ whiteSpace: 'nowrap' }}>{fmt(detail.closed_at)}</Descriptions.Item>
          <Descriptions.Item label={t('itsm.ticket.slaResponseTarget')}>
            {detail.sla_response_min != null ? t('itsm.unit.minutes', { n: detail.sla_response_min }) : '-'}
          </Descriptions.Item>
          <Descriptions.Item label={t('itsm.ticket.actualResponse')}>
            {detail.actual_response_min != null ? (
              <Space>
                {t('itsm.unit.minutes', { n: detail.actual_response_min })}
                {detail.sla_response_met === true && <Tag color="green">{t('itsm.sla.met')}</Tag>}
                {detail.sla_response_met === false && <Tag color="red">{t('itsm.sla.overdue')}</Tag>}
              </Space>
            ) : (
              '-'
            )}
          </Descriptions.Item>
          <Descriptions.Item label={t('itsm.ticket.slaResolutionTarget')}>
            {detail.sla_resolution_hours != null ? t('itsm.unit.hours', { n: detail.sla_resolution_hours }) : '-'}
          </Descriptions.Item>
          <Descriptions.Item label={t('itsm.ticket.actualResolution')}>
            {detail.actual_resolution_hours != null ? (
              <Space>
                {t('itsm.unit.hours', { n: detail.actual_resolution_hours })}
                {detail.sla_resolution_met === true && <Tag color="green">{t('itsm.sla.met')}</Tag>}
                {detail.sla_resolution_met === false && <Tag color="red">{t('itsm.sla.overdue')}</Tag>}
                {detail.sla_resolution_met == null && detail.sla_warned && <Tag color="orange">{t('itsm.sla.due')}</Tag>}
              </Space>
            ) : detail.sla_warned ? (
              <Tag color="orange">{t('itsm.sla.dueMark')}</Tag>
            ) : (
              '-'
            )}
          </Descriptions.Item>
          <Descriptions.Item label={t('itsm.ticket.reopenCount')}>{detail.reopen_count ?? 0}</Descriptions.Item>
          <Descriptions.Item label={t('itsm.ticket.firstTimeFix')}>
            {detail.first_time_fix == null ? '-' : detail.first_time_fix ? t('common.yes') : t('common.no')}
          </Descriptions.Item>
          <Descriptions.Item label={t('itsm.ticket.pausedDuration')}>
            {detail.paused_minutes != null ? t('itsm.unit.minutes', { n: detail.paused_minutes }) : '-'}
          </Descriptions.Item>
          <Descriptions.Item label={t('itsm.ticket.satisfaction')}>
            {detail.satisfaction != null ? (
              <Space direction="vertical" size={4}>
                <Rate disabled value={detail.satisfaction} />
                {!!detail.satisfaction_detail?.tags?.length && (
                  <Space size={4} wrap>
                    {detail.satisfaction_detail.tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}
                  </Space>
                )}
                {detail.satisfaction_detail?.comment && (
                  <Typography.Text type="secondary">{detail.satisfaction_detail.comment}</Typography.Text>
                )}
              </Space>
            ) : '-'}
          </Descriptions.Item>
          <Descriptions.Item label={t('itsm.f.description')} span={2}>
            <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
              {detail.description || '-'}
            </Typography.Paragraph>
          </Descriptions.Item>
          {detail.remarks && (
            <Descriptions.Item label={t('common.remark')} span={2}>
              {detail.remarks}
            </Descriptions.Item>
          )}
          {detail.closure_code && (
            <Descriptions.Item label={t('itsm.ticket.closureCode')} span={2}>
              {detail.closure_code}
            </Descriptions.Item>
          )}
        </Descriptions>
      </Card>

      {isChange && (
        <Card title={t('itsm.ticket.changeInfo')} size="small">
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label={t('itsm.ticket.changeType')}>{detail.change_type ? et.changeType(detail.change_type) : '-'}</Descriptions.Item>
            <Descriptions.Item label={t('itsm.ticket.riskLevel')}>{detail.risk_level ? et.riskGrade(detail.risk_level) : '-'}</Descriptions.Item>
            <Descriptions.Item label={t('itsm.ticket.plannedStart')} contentStyle={{ whiteSpace: 'nowrap' }}>{fmt(detail.planned_start_at)}</Descriptions.Item>
            <Descriptions.Item label={t('itsm.ticket.plannedEnd')} contentStyle={{ whiteSpace: 'nowrap' }}>{fmt(detail.planned_end_at)}</Descriptions.Item>
            <Descriptions.Item label={t('itsm.ticket.changeReason')} span={2}>
              {detail.change_reason ?? '-'}
            </Descriptions.Item>
            <Descriptions.Item label={t('itsm.ticket.rollbackPlan')} span={2}>
              {detail.rollback_plan ?? '-'}
            </Descriptions.Item>
            <Descriptions.Item label={t('itsm.ticket.implementationPlan')} span={2}>
              {detail.implementation_plan ?? '-'}
            </Descriptions.Item>
            <Descriptions.Item label={t('itsm.ticket.approvedAt')} contentStyle={{ whiteSpace: 'nowrap' }}>{fmt(detail.approved_at)}</Descriptions.Item>
            <Descriptions.Item label={t('itsm.ticket.approvalComment')}>{detail.approval_comment ?? '-'}</Descriptions.Item>
          </Descriptions>
        </Card>
      )}

      {(detail.solution || detail.root_cause) && (
        <Card title={t('itsm.ticket.solutionRootCause')} size="small">
          <Descriptions column={1} size="small" bordered>
            {detail.solution && (
              <Descriptions.Item label={t('itsm.ticket.solution')}>
                <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                  {detail.solution}
                </Typography.Paragraph>
              </Descriptions.Item>
            )}
            {detail.root_cause && (
              <Descriptions.Item label={t('itsm.ticket.rootCause')}>
                <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                  {detail.root_cause}
                </Typography.Paragraph>
              </Descriptions.Item>
            )}
          </Descriptions>
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
                label={t('itsm.ticket.solution')}
                rules={[{ required: true, message: t('itsm.ticket.solutionRequired') }]}
              >
                <Input.TextArea rows={4} maxLength={2000} />
              </Form.Item>
              <Form.Item name="root_cause" label={t('itsm.ticket.rootCauseOptional')}>
                <Input.TextArea rows={3} maxLength={2000} />
              </Form.Item>
            </>
          )}
          {transition?.to === 'closed' && (
            <Form.Item
              name="closure_code"
              label={t('itsm.ticket.closureCode')}
              rules={[{ required: true, message: t('itsm.ticket.closureCodeRequired') }]}
            >
              <Select
                placeholder={t('itsm.ticket.closureCodePlaceholder')}
                options={closureCodes.map((c) => ({ value: c.code, label: c.name }))}
              />
            </Form.Item>
          )}
          {(transition?.to === 'approved' || transition?.to === 'rejected') && (
            <Form.Item name="approval_comment" label={t('itsm.ticket.approvalComment')}>
              <Input.TextArea rows={3} maxLength={1000} />
            </Form.Item>
          )}
        </Form>
      </Modal>

      {/* 改派 Modal */}
      <Modal
        title={t('itsm.ticket.reassignTitle')}
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
          placeholder={t('itsm.ticket.reassignPlaceholder')}
          value={reassignTo}
          onChange={setReassignTo}
          options={members.map((m) => ({
            value: m.id,
            label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
          }))}
        />
      </Modal>

      {/* 完成流程步骤 Modal */}
      <Modal
        title={completingTask ? t('itsm.completeStepTitle', { name: completingTask.name }) : ''}
        open={!!completingTask}
        onOk={() => void submitTaskComplete()}
        confirmLoading={taskSaving}
        onCancel={() => setCompletingTask(null)}
        destroyOnClose
      >
        <Input.TextArea
          rows={3}
          maxLength={500}
          placeholder={t('itsm.taskCommentPlaceholder')}
          value={taskComment}
          onChange={(e) => setTaskComment(e.target.value)}
        />
      </Modal>
          <Modal
        title={`${t('itsm.ticket.closeTitle')} · ${detail.ticket_code}`}
        open={closeOpen}
        confirmLoading={closeSaving}
        okButtonProps={{ danger: true }}
        onOk={async () => {
          if (closeReason.trim().length < 5) {
            message.warning(t('itsm.ticket.closeReasonRequired'));
            return;
          }
          setCloseSaving(true);
          try {
            await api.post(`/tickets/${id}/close`, { reason: closeReason.trim() });
            message.success(t('itsm.ticket.closedMsg'));
            setCloseOpen(false);
            void load();
          } catch {
            // 已统一提示
          } finally {
            setCloseSaving(false);
          }
        }}
        onCancel={() => setCloseOpen(false)}
        destroyOnClose
      >
        <div style={{ marginBottom: 8 }}>{t('itsm.ticket.closeReason')}</div>
        <Input.TextArea rows={3} maxLength={500} value={closeReason} onChange={(e) => setCloseReason(e.target.value)}
          placeholder={t('itsm.ticket.closeReasonPlaceholder')} />
      </Modal>
</Space>
  );
}
