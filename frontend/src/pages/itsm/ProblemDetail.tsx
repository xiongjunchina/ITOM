import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  Badge,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Spin,
  Steps,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ArrowLeftOutlined, LinkOutlined } from '@ant-design/icons';
import { useGoBack } from '../../utils/nav';
import dayjs from 'dayjs';
import { api } from '../../api/client';
import { ExampleAlert } from '../../components/ExampleTag';
import type {
  AllowedTransition,
  LinkedTicketBrief,
  ProblemDetail as ProblemDetailData,
  ProcessStep,
  TicketRow,
} from '../../api/types';
import { PRIORITY_COLORS } from '../../api/types';
import { useRoleOptions } from '../../utils/roleOptions';
import { useT } from '../../i18n';
import { problemStatusBadge } from './Problems';

const fmt = (v?: string | null) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-');

function stepStatus(s: ProcessStep): 'finish' | 'process' | 'wait' {
  if (s.task_status === '已完成') return 'finish';
  if (s.task_status === '待处理') return 'process';
  return 'wait';
}

/** 转已知错误/已解决时必须提供根因 */
const NEEDS_ROOT_CAUSE = new Set(['known_error', 'resolved']);

export default function ProblemDetail() {
  const { id } = useParams<{ id: string }>();
  const goBack = useGoBack();
  const t = useT();

  /** 角色/组 code → 中文名（流程条处理人与知会人展示） */
  const { roleLabel } = useRoleOptions();

  const [detail, setDetail] = useState<ProblemDetailData | null>(null);
  const [loading, setLoading] = useState(true);

  // 状态流转 Modal（根因/规避）
  const [transition, setTransition] = useState<AllowedTransition | null>(null);
  const [transForm] = Form.useForm<{ root_cause: string; workaround?: string }>();
  const [transSaving, setTransSaving] = useState(false);

  // 关联工单 Modal
  const [linkOpen, setLinkOpen] = useState(false);
  const [linkTicketId, setLinkTicketId] = useState<string | undefined>();
  const [linkSaving, setLinkSaving] = useState(false);
  const [ticketOptions, setTicketOptions] = useState<TicketRow[]>([]);
  const [ticketSearching, setTicketSearching] = useState(false);

  // 完成流程步骤
  const [completingTask, setCompletingTask] = useState<ProcessStep | null>(null);
  const [taskComment, setTaskComment] = useState('');
  const [taskSaving, setTaskSaving] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const data = await api.get<ProblemDetailData>(`/problems/${id}`);
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

  const openTransition = (tr: AllowedTransition) => {
    if (!NEEDS_ROOT_CAUSE.has(tr.to)) {
      Modal.confirm({
        title: t('itsm.confirmAction', { name: tr.to_name }),
        onOk: async () => {
          await api.post(`/problems/${id}/transition`, { to: tr.to, fields: {} });
          message.success(t('itsm.actionOk'));
          void load();
        },
      });
      return;
    }
    transForm.resetFields();
    transForm.setFieldsValue({
      root_cause: detail?.root_cause ?? '',
      workaround: detail?.workaround ?? '',
    });
    setTransition(tr);
  };

  const submitTransition = async () => {
    if (!transition) return;
    const values = await transForm.validateFields();
    const fields: Record<string, unknown> = { root_cause: values.root_cause };
    if (values.workaround) fields.workaround = values.workaround;
    setTransSaving(true);
    try {
      await api.post(`/problems/${id}/transition`, { to: transition.to, fields });
      message.success(t('itsm.actionOk'));
      setTransition(null);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setTransSaving(false);
    }
  };

  const searchTickets = (kw: string) => {
    setTicketSearching(true);
    api
      .getList<TicketRow>('/tickets', { page: 1, page_size: 20, q: kw || undefined })
      .then((res) => setTicketOptions(res.items))
      .catch(() => undefined)
      .finally(() => setTicketSearching(false));
  };

  const openLink = () => {
    setLinkTicketId(undefined);
    setLinkOpen(true);
    searchTickets('');
  };

  const submitLink = async () => {
    if (!linkTicketId) {
      message.warning(t('itsm.problem.selectTicketToLink'));
      return;
    }
    setLinkSaving(true);
    try {
      await api.post(`/problems/${id}/link-ticket`, { ticket_id: linkTicketId });
      message.success(t('itsm.problem.ticketLinked'));
      setLinkOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setLinkSaving(false);
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
        <Typography.Text type="secondary">{t('itsm.problem.notFound')}</Typography.Text>
      </Card>
    );
  }

  /** 示例数据只读：隐藏关联工单/完成步骤等残余写入口（allowed_transitions 后端已置空） */
  const isExample = detail.is_example === true;
  const process = detail.process;

  const linkedColumns: ColumnsType<LinkedTicketBrief> = [
    {
      title: t('itsm.problem.ticketCode'),
      dataIndex: 'ticket_code',
      width: 160,
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (v: string, r) => <Link to={`/itsm/tickets/${r.id}`}>{v}</Link>,
    },
    { title: t('itsm.f.title'), dataIndex: 'title', ellipsis: true },
    { title: t('common.status'), dataIndex: 'status', width: 140, render: (v?: string) => v || '-' },
  ];

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {isExample && <ExampleAlert />}
      <Card>
        <Space style={{ width: '100%', justifyContent: 'space-between', flexWrap: 'wrap' }}>
          <Space size="middle" wrap>
            <Button icon={<ArrowLeftOutlined />} onClick={() => goBack('/itsm/problems')}>
              {t('itsm.back')}
            </Button>
            <Typography.Title level={4} style={{ margin: 0 }}>
              {detail.problem_code} · {detail.title}
            </Typography.Title>
            <Badge status={problemStatusBadge(detail.status)} text={detail.status_name || detail.status} />
            <Tag color={PRIORITY_COLORS[detail.priority]}>{detail.priority}</Tag>
          </Space>
          <Space wrap>
            {(detail.allowed_transitions ?? []).map((tr) => (
              <Button key={tr.to} type="primary" onClick={() => openTransition(tr)}>
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
              title: s.name,
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
                  {s.task_status === '待处理' && s.task_id != null && !isExample && (
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
          <Descriptions.Item label={t('itsm.f.owner')}>{detail.owner_name ?? '-'}</Descriptions.Item>
          <Descriptions.Item label={t('itsm.f.createdAt')} contentStyle={{ whiteSpace: 'nowrap' }}>{fmt(detail.created_at)}</Descriptions.Item>
          <Descriptions.Item label={t('itsm.problem.sourceTicket')}>
            {detail.source_ticket_id ? (
              <Link to={`/itsm/tickets/${detail.source_ticket_id}`}>
                {detail.linked_tickets.find((lt) => lt.id === detail.source_ticket_id)?.ticket_code ?? t('itsm.view')}
              </Link>
            ) : (
              '-'
            )}
          </Descriptions.Item>
          <Descriptions.Item label={t('itsm.f.description')} span={2}>
            <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
              {detail.description || '-'}
            </Typography.Paragraph>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title={t('itsm.problem.rootCauseCard')} size="small">
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label={t('itsm.ticket.rootCause')}>
            {detail.root_cause ? (
              <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                {detail.root_cause}
              </Typography.Paragraph>
            ) : (
              <Typography.Text type="secondary">{t('itsm.problem.rootCauseHint')}</Typography.Text>
            )}
          </Descriptions.Item>
          <Descriptions.Item label={t('itsm.problem.workaround')}>
            {detail.workaround ? (
              <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                {detail.workaround}
              </Typography.Paragraph>
            ) : (
              <Typography.Text type="secondary">{t('itsm.none')}</Typography.Text>
            )}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card
        title={t('itsm.problem.linkedTicketsCount', { n: detail.linked_tickets.length })}
        size="small"
        extra={
          !isExample && (
            <Button icon={<LinkOutlined />} onClick={openLink}>
              {t('itsm.problem.linkTicket')}
            </Button>
          )
        }
      >
        <Table<LinkedTicketBrief>
          rowKey="id"
          size="small"
          columns={linkedColumns}
          dataSource={detail.linked_tickets}
          pagination={false}
          locale={{ emptyText: t('itsm.noLinkedTickets') }}
        />
      </Card>

      {/* 状态流转 Modal：根因 + 规避 */}
      <Modal
        title={transition ? t('itsm.problem.transModalTitle', { name: transition.to_name }) : ''}
        open={!!transition}
        onOk={() => void submitTransition()}
        confirmLoading={transSaving}
        onCancel={() => setTransition(null)}
        destroyOnClose
      >
        <Form form={transForm} layout="vertical" preserve={false}>
          <Form.Item name="root_cause" label={t('itsm.ticket.rootCause')} rules={[{ required: true, message: t('itsm.problem.rootCauseRequired') }]}>
            <Input.TextArea rows={4} maxLength={2000} placeholder={t('itsm.problem.rootCausePlaceholder')} />
          </Form.Item>
          <Form.Item name="workaround" label={t('itsm.problem.workaroundOptional')}>
            <Input.TextArea rows={3} maxLength={2000} placeholder={t('itsm.problem.workaroundPlaceholder')} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 关联工单 Modal */}
      <Modal
        title={t('itsm.problem.linkTicket')}
        open={linkOpen}
        onOk={() => void submitLink()}
        confirmLoading={linkSaving}
        onCancel={() => setLinkOpen(false)}
        destroyOnClose
      >
        <Select
          style={{ width: '100%' }}
          showSearch
          filterOption={false}
          loading={ticketSearching}
          placeholder={t('itsm.problem.searchTicketPlaceholder')}
          value={linkTicketId}
          onChange={setLinkTicketId}
          onSearch={searchTickets}
          notFoundContent={ticketSearching ? <Spin size="small" /> : t('itsm.problem.noMatchTicket')}
          options={ticketOptions.map((t) => ({
            value: t.id,
            label: `${t.ticket_code} ${t.title}`,
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
    </Space>
  );
}
