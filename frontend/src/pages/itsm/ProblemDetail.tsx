import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
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
import dayjs from 'dayjs';
import { api } from '../../api/client';
import type {
  AllowedTransition,
  LinkedTicketBrief,
  ProblemDetail as ProblemDetailData,
  ProcessStep,
  TicketRow,
} from '../../api/types';
import { PRIORITY_COLORS } from '../../api/types';
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
  const navigate = useNavigate();

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

  const openTransition = (t: AllowedTransition) => {
    if (!NEEDS_ROOT_CAUSE.has(t.to)) {
      Modal.confirm({
        title: `确认执行「${t.to_name}」？`,
        onOk: async () => {
          await api.post(`/problems/${id}/transition`, { to: t.to, fields: {} });
          message.success('操作成功');
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
    setTransition(t);
  };

  const submitTransition = async () => {
    if (!transition) return;
    const values = await transForm.validateFields();
    const fields: Record<string, unknown> = { root_cause: values.root_cause };
    if (values.workaround) fields.workaround = values.workaround;
    setTransSaving(true);
    try {
      await api.post(`/problems/${id}/transition`, { to: transition.to, fields });
      message.success('操作成功');
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
      message.warning('请选择要关联的工单');
      return;
    }
    setLinkSaving(true);
    try {
      await api.post(`/problems/${id}/link-ticket`, { ticket_id: linkTicketId });
      message.success('工单已关联');
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
        <Typography.Text type="secondary">问题不存在或无权查看</Typography.Text>
      </Card>
    );
  }

  const process = detail.process;

  const linkedColumns: ColumnsType<LinkedTicketBrief> = [
    {
      title: '工单编号',
      dataIndex: 'ticket_code',
      width: 160,
      render: (v: string, r) => <Link to={`/itsm/tickets/${r.id}`}>{v}</Link>,
    },
    { title: '标题', dataIndex: 'title', ellipsis: true },
    { title: '状态', dataIndex: 'status', width: 140, render: (v?: string) => v || '-' },
  ];

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card>
        <Space style={{ width: '100%', justifyContent: 'space-between', flexWrap: 'wrap' }}>
          <Space size="middle" wrap>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/itsm/problems')}>
              返回
            </Button>
            <Typography.Title level={4} style={{ margin: 0 }}>
              {detail.problem_code} · {detail.title}
            </Typography.Title>
            <Badge status={problemStatusBadge(detail.status)} text={detail.status_name || detail.status} />
            <Tag color={PRIORITY_COLORS[detail.priority]}>{detail.priority}</Tag>
          </Space>
          <Space wrap>
            {(detail.allowed_transitions ?? []).map((t) => (
              <Button key={t.to} type="primary" onClick={() => openTransition(t)}>
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
          <Descriptions.Item label="负责人">{detail.owner_name ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{fmt(detail.created_at)}</Descriptions.Item>
          <Descriptions.Item label="来源工单">
            {detail.source_ticket_id ? (
              <Link to={`/itsm/tickets/${detail.source_ticket_id}`}>
                {detail.linked_tickets.find((t) => t.id === detail.source_ticket_id)?.ticket_code ?? '查看'}
              </Link>
            ) : (
              '-'
            )}
          </Descriptions.Item>
          <Descriptions.Item label="描述" span={2}>
            <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
              {detail.description || '-'}
            </Typography.Paragraph>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="根因 / 规避方案" size="small">
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="根因">
            {detail.root_cause ? (
              <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                {detail.root_cause}
              </Typography.Paragraph>
            ) : (
              <Typography.Text type="secondary">待分析（转「已知错误/已解决」时填写）</Typography.Text>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="临时规避">
            {detail.workaround ? (
              <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                {detail.workaround}
              </Typography.Paragraph>
            ) : (
              <Typography.Text type="secondary">暂无</Typography.Text>
            )}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card
        title={`关联工单（${detail.linked_tickets.length}）`}
        size="small"
        extra={
          <Button icon={<LinkOutlined />} onClick={openLink}>
            关联工单
          </Button>
        }
      >
        <Table<LinkedTicketBrief>
          rowKey="id"
          size="small"
          columns={linkedColumns}
          dataSource={detail.linked_tickets}
          pagination={false}
          locale={{ emptyText: '暂无关联工单' }}
        />
      </Card>

      {/* 状态流转 Modal：根因 + 规避 */}
      <Modal
        title={transition ? `${transition.to_name} — 填写根因` : ''}
        open={!!transition}
        onOk={() => void submitTransition()}
        confirmLoading={transSaving}
        onCancel={() => setTransition(null)}
        destroyOnClose
      >
        <Form form={transForm} layout="vertical" preserve={false}>
          <Form.Item name="root_cause" label="根因" rules={[{ required: true, message: '请填写根因' }]}>
            <Input.TextArea rows={4} maxLength={2000} placeholder="问题的根本原因分析" />
          </Form.Item>
          <Form.Item name="workaround" label="临时规避（可选）">
            <Input.TextArea rows={3} maxLength={2000} placeholder="根治前的临时规避方案" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 关联工单 Modal */}
      <Modal
        title="关联工单"
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
          placeholder="输入编号/标题搜索工单"
          value={linkTicketId}
          onChange={setLinkTicketId}
          onSearch={searchTickets}
          notFoundContent={ticketSearching ? <Spin size="small" /> : '无匹配工单'}
          options={ticketOptions.map((t) => ({
            value: t.id,
            label: `${t.ticket_code} ${t.title}`,
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
