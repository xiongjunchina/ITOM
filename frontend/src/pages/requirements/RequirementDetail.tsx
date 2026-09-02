import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  Alert,
  Button,
  Card,
  Checkbox,
  DatePicker,
  Descriptions,
  Divider,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Progress,
  Radio,
  Segmented,
  Select,
  Space,
  Spin,
  Steps,
  Tag,
  Tooltip,
  Typography,
  Upload,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import Table from '../../components/SortableTable';
import {
  ArrowLeftOutlined,
  BookOutlined,
  DeleteOutlined,
  EditOutlined,
  ExportOutlined,
  PaperClipOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { api } from '../../api/client';
import { useGoBack } from '../../utils/nav';
import { useProcessTaskView } from '../../utils/processTaskView';
import { isRequesterOnly } from '../../components/menu';
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';
import { ExampleAlert } from '../../components/ExampleTag';
import DocumentTypeHint from '../../components/DocumentTypeHint';
import RecordRelationCreateButton from '../../components/RecordRelationCreateButton';
import RecordRelationsPanel from '../../components/RecordRelationsPanel';
import { useAuthStore } from '../../stores/auth';
import InvestmentPanel from '../../components/investment/InvestmentPanel';
import { useRoleOptions } from '../../utils/roleOptions';
import FlowDiagram from '../../components/FlowDiagram';
import type { FlowDiagramStep } from '../../components/FlowDiagram';
import CompleteStepModal from '../../components/CompleteStepModal';
import ProcessActionButtons from '../../components/ProcessActionButtons';
import type {
  AcceptanceCriterion,
  AttachmentItem,
  AllowedTransition,
  BusinessDomain,
  MasterDataItem,
  Member,
  ProjectRow,
  RequirementDetail as RequirementDetailData,
  RequirementTask,
  RequirementTaskStatus,
  ScoringConfig,
} from '../../api/types';
import {
  MOSCOW_KEYS,
  REQ_DECISIONS,
  REQ_TASK_STATUSES,
  REQ_TASK_STATUS_COLORS,
  REQ_TYPES,
  ROUTE_DEV,
  ROUTE_PROJECT,
  SOLUTION_TYPES,
} from '../../api/types';
import { DecisionTag, MoscowTag, QuadrantTag, ReqStatusBadge, RouteTag, fmtDt } from './shared';
import { shouldLoadRequirementTaskMembers } from './developmentTaskOptions';
import { DIMENSIONS, computeRoute, computeScore, type DimScores } from './dimensions';

// ---------- 评估评分面板 ----------

function EvaluationPanel({
  id,
  detail,
  editable,
  onSaved,
}: {
  id: string;
  detail: RequirementDetailData;
  editable: boolean;
  onSaved: () => void;
}) {
  const t = useT();
  const et = useEnums();
  const { roleLabel } = useRoleOptions();
  const [config, setConfig] = useState<ScoringConfig | null>(null);

  // 当前评分只认有效共识行。退回评审或登记人时，旧行保留为历史，
  // 不得再回填为当前评分。导入数据若只有主表分数，仍由 persistedScores 兼容。
  const scoreRecord = useMemo(() => {
    const list = detail.scores ?? [];
    return list.find((s) => s.is_consensus) ?? null;
  }, [detail.scores]);

  const persistedScores = useMemo<DimScores>(() => {
    if (scoreRecord) {
      return {
        d1_strategy: scoreRecord.d1_strategy ?? undefined,
        d2_value: scoreRecord.d2_value ?? undefined,
        d3_tech: scoreRecord.d3_tech ?? undefined,
        d4_org: scoreRecord.d4_org ?? undefined,
        d5_risk: scoreRecord.d5_risk ?? undefined,
      };
    }
    return {
      d1_strategy: detail.d1_strategy ?? undefined,
      d2_value: detail.d2_value ?? undefined,
      d3_tech: detail.d3_tech ?? undefined,
      d4_org: detail.d4_org ?? undefined,
      d5_risk: detail.d5_risk ?? undefined,
    };
  }, [
    detail.d1_strategy,
    detail.d2_value,
    detail.d3_tech,
    detail.d4_org,
    detail.d5_risk,
    scoreRecord,
  ]);

  const [scores, setScores] = useState<DimScores>({});
  const [decision, setDecision] = useState<string | undefined>(detail.decision ?? undefined);
  const [comment, setComment] = useState<string>('');
  const [returnToSeq, setReturnToSeq] = useState<number | undefined>(detail.process?.return_targets?.[0]?.seq);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setScores(persistedScores);
    setComment(scoreRecord?.comment ?? '');
    setDecision(detail.decision ?? undefined);
    setReturnToSeq(detail.process?.return_targets?.[0]?.seq);
  }, [persistedScores, scoreRecord, detail.decision, detail.process?.return_targets]);

  useEffect(() => {
    api
      .get<ScoringConfig>('/requirements/scoring-config')
      .then(setConfig)
      .catch(() => message.error(t('req.scoreLoadFailed')));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const preview = useMemo(
    () => (config ? computeScore(scores, config.weights, config.thresholds) : null),
    [scores, config],
  );

  // 评分配置仍在加载或历史主表评分无法由前端立即重算时，优先展示后端已计算的权威结果。
  const displayPreview = preview ?? (
    detail.weighted_total != null && detail.quadrant
      ? { total: detail.weighted_total, quadrant: detail.quadrant }
      : null
  );

  // 与后端契约保持一致：通过需完成五维评分且不得落入重新评估；搁置和驳回均可用，驳回必须填写理由。
  const isReeval = displayPreview?.quadrant === '重新评估';
  const decisionDisabled = (d: string): boolean =>
    d === '通过' ? !displayPreview || isReeval : false;
  const decisionDisabledTip = (d: string): string =>
    d === '通过'
      ? isReeval
        ? t('req.eval.quadrantBlocked')
        : t('req.eval.needFullScores')
      : '';

  // 打分变化导致象限变化时，已选决议若被禁用则自动清空，避免提交无效决议
  useEffect(() => {
    if (editable && decision && decisionDisabled(decision)) setDecision(undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editable, decision, displayPreview?.quadrant]);

  /** 驳回必填理由（≥5 字，前端校验 + 后端 REASON_REQUIRED 兜底） */
  const rejectCommentInvalid = decision === '驳回' && comment.trim().length < 5;

  const submit = async () => {
    if (rejectCommentInvalid) {
      message.error(t('req.eval.rejectReasonRequired'));
      return;
    }
    setSaving(true);
    try {
      const body: Record<string, unknown> = { comment: comment || null };
      DIMENSIONS.forEach((d) => {
        if (scores[d.key] != null) body[d.key] = scores[d.key];
      });
      if (decision) body.decision = decision;
      if (decision === '驳回' && returnToSeq != null) body.return_to_seq = returnToSeq;
      // 决议保存即自动流转（M16）：按返回 flowed_to 提示去向
      const res = await api.post<{ status: string; flowed_to: string | null }>(
        `/requirements/${id}/score`,
        body,
      );
      message.success(
        res.flowed_to === 'analyzing'
          ? t('req.eval.flowedAnalyzing')
          : res.flowed_to === 'on_hold'
            ? t('req.eval.flowedOnHold')
            : res.flowed_to === 'supplementing'
              ? t('req.eval.flowedSupplementing')
              : res.flowed_to === 'evaluating'
                ? t('req.eval.flowedEvaluating')
              : t('req.scoreSaved'),
      );
      onSaved();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const scoreOptions = [1, 2, 3, 4, 5].map((n) => ({ value: n, label: String(n) }));

  return (
    <Card title={t('req.evaluation')} size="small">
      <Alert
        type={editable ? 'info' : 'success'}
        showIcon
        style={{ marginBottom: 16 }}
        message={editable ? t('req.evalGateHint') : t('req.evalHistoricalHint')}
        description={(
          <span>
            {t('req.evalScoringRulesHint')} <Link to="/requirements/scoring">{t('req.tab.scoring')}</Link>
          </span>
        )}
      />

      <Typography.Text strong>{t('req.evalScore')}</Typography.Text>
      <div style={{ marginTop: 12 }}>
        {DIMENSIONS.map((d) => {
          const cur = scores[d.key];
          const rubric = config?.rubric?.[d.short];
          const levelText = cur != null && rubric ? (rubric as unknown as Record<string, string>)[String(cur)] : undefined;
          return (
            <div key={d.key} style={{ padding: '8px 0', borderBottom: '1px solid #f0f0f0' }}>
              <Space wrap style={{ width: '100%', justifyContent: 'space-between' }} align="start">
                <Space size={6}>
                  <Typography.Text strong>
                    {d.code} · {t(d.nameKey)}
                  </Typography.Text>
                  {d.reverse && (
                    <Tooltip title={t('req.dimReverseHint')}>
                      <Tag color="orange" style={{ marginInlineEnd: 0 }}>
                        {t('req.dimReverse')}
                      </Tag>
                    </Tooltip>
                  )}
                </Space>
                <Segmented
                  options={scoreOptions}
                  value={cur}
                  disabled={!editable}
                  onChange={(v) => setScores((s) => ({ ...s, [d.key]: v as number }))}
                />
              </Space>
              {levelText && (
                <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
                  {levelText}
                </Typography.Text>
              )}
            </div>
          );
        })}
      </div>

      {/* 实时预览：加权总分 + 象限 */}
      <div style={{ margin: '16px 0', display: 'flex', gap: 24, alignItems: 'center', flexWrap: 'wrap' }}>
        {displayPreview ? (
          <>
            <Space direction="vertical" size={0}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {t('req.weightedTotal')}
              </Typography.Text>
              <Typography.Title level={3} style={{ margin: 0 }}>
                {displayPreview.total.toFixed(1)}
              </Typography.Title>
            </Space>
            <Space direction="vertical" size={4}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {t('req.quadrant')}
              </Typography.Text>
              <QuadrantTag value={displayPreview.quadrant} />
            </Space>
          </>
        ) : (
          <Typography.Text type="secondary">{t('req.previewHint')}</Typography.Text>
        )}
      </div>

      {/* 决议 + 备注 + 保存（决议保存即自动流转） */}
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Space wrap align="center">
          <Typography.Text strong>{t('req.evalDecision')}</Typography.Text>
          {editable ? (
            <Select
              allowClear
              placeholder={t('req.selectDecision')}
              style={{ width: 160 }}
              value={decision}
              onChange={(v) => setDecision(v)}
              options={REQ_DECISIONS.map((dv) => {
                const disabled = decisionDisabled(dv);
                const destKey = dv === '通过' ? 'req.eval.dest.approve' : dv === '搁置' ? 'req.eval.dest.hold' : 'req.eval.dest.reject';
                const text = `${et.reqDecision(dv)}${t(destKey)}`;
                return {
                  value: dv,
                  disabled,
                  label: disabled ? (
                    <Tooltip title={decisionDisabledTip(dv)}>
                      <span>{text}</span>
                    </Tooltip>
                  ) : (
                    text
                  ),
                };
              })}
            />
          ) : (
            <DecisionTag value={detail.decision} />
          )}
        </Space>
        {editable && isReeval && (
          <Typography.Text type="warning" style={{ fontSize: 12 }}>
            {t('req.eval.quadrantBlocked')}
          </Typography.Text>
        )}
        {editable && decision === '驳回' && (detail.process?.return_targets?.length ?? 0) > 0 && (
          <Space wrap align="center">
            <Typography.Text strong>{t('req.eval.returnTarget')}</Typography.Text>
            <Select
              style={{ minWidth: 240 }}
              value={returnToSeq}
              onChange={setReturnToSeq}
              options={detail.process!.return_targets!.map((target) => ({
                value: target.seq,
                label: target.name,
              }))}
            />
          </Space>
        )}
        {editable ? (
          <>
            <Input.TextArea
              rows={2}
              maxLength={1000}
              value={comment}
              status={rejectCommentInvalid ? 'error' : undefined}
              placeholder={
                decision === '驳回'
                  ? t('req.eval.rejectReasonRequired')
                  : decision === '搁置'
                    ? t('req.eval.holdCommentHint')
                    : t('req.scoreCommentPlaceholder')
              }
              onChange={(e) => setComment(e.target.value)}
            />
            {rejectCommentInvalid && (
              <Typography.Text type="danger" style={{ fontSize: 12 }}>
                {t('req.eval.rejectReasonRequired')}
              </Typography.Text>
            )}
          </>
        ) : (
          scoreRecord?.comment && (
            <Typography.Paragraph type="secondary" style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
              {scoreRecord.comment}
            </Typography.Paragraph>
          )
        )}
        {editable && (
          <Button type="primary" loading={saving} onClick={() => void submit()}>
            {t('req.eval.saveFlow')}
          </Button>
        )}
      </Space>

      {/* 评分记录（多评审人时列出） */}
      {(detail.scores?.length ?? 0) > 1 && (
        <>
          <Divider />
          <Typography.Text strong>{t('req.scoreHistory')}</Typography.Text>
          <div style={{ marginTop: 8 }}>
            {detail.scores!.map((s, i) => (
              <div key={i} style={{ padding: '4px 0' }}>
                <Space size={6} wrap>
                  <Tag>{s.reviewer_name || t('req.reviewer')}</Tag>
                  {s.reviewer_role && <Typography.Text type="secondary">{roleLabel(s.reviewer_role)}</Typography.Text>}
                  {s.is_consensus && <Tag color="blue">{t('req.consensus')}</Tag>}
                  <Typography.Text>
                    {DIMENSIONS.map((d) => (s as unknown as Record<string, number>)[d.key]).join(' / ')}
                  </Typography.Text>
                  {s.comment && <Typography.Text type="secondary">— {s.comment}</Typography.Text>}
                </Space>
              </div>
            ))}
          </div>
        </>
      )}
    </Card>
  );
}

// ---------- 方案评估区（M16）：方案类型 + 开发人天 → 实现路径分流 ----------

function SolutionEvalSection({
  id,
  detail,
  editable,
  isAnalyzing,
  canOperate,
  memberOptions,
  onPatch,
  onSaved,
}: {
  id: string;
  detail: RequirementDetailData;
  /** 字段可编辑（有编辑权且非终态） */
  editable: boolean;
  /** 当前处于方案评估阶段（analyzing）：显示转项目按钮/排期提示 */
  isAnalyzing: boolean;
  /** 可执行转项目操作（编辑权且非示例数据） */
  canOperate: boolean;
  memberOptions: { value: string; label: string }[];
  onPatch: (patch: Record<string, unknown>, okMsg?: string) => Promise<void>;
  onSaved: () => void;
}) {
  const t = useT();
  const et = useEnums();
  const [config, setConfig] = useState<ScoringConfig | null>(null);
  const [devEffort, setDevEffort] = useState<number | null>(detail.dev_effort ?? null);
  useEffect(() => {
    setDevEffort(detail.dev_effort ?? null);
  }, [detail.dev_effort]);
  useEffect(() => {
    api
      .get<ScoringConfig>('/requirements/scoring-config')
      .then(setConfig)
      .catch(() => undefined);
  }, []);

  const threshold = config?.effort_threshold ?? 20;
  // 实时路径徽标：按本地输入即时判定（与后端 compute_route 一致，保存后以详情返回为准）
  const route = computeRoute(detail.solution_type, devEffort, threshold);
  const basis = !detail.solution_type
    ? t('req.solution.noType')
    : detail.solution_type === '新购系统'
      ? t('req.solution.basisNewSystem')
      : devEffort == null
        ? t('req.solution.basisDevEmpty', { th: threshold })
        : devEffort >= threshold
          ? t('req.solution.basisDevGte', { n: devEffort, th: threshold })
          : t('req.solution.basisDevLt', { n: devEffort, th: threshold });

  // 转项目管理：Modal 选 PM → POST to-project
  const [pmOpen, setPmOpen] = useState(false);
  const [pmSaving, setPmSaving] = useState(false);
  const [pmForm] = Form.useForm();

  const submitToProject = async () => {
    const v = await pmForm.validateFields();
    setPmSaving(true);
    try {
      await api.post(`/requirements/${id}/to-project`, { pm_id: v.pm_id });
      message.success(t('req.solution.toProjectDone'));
      setPmOpen(false);
      onSaved();
    } catch {
      // ROUTE_STAGE / ROUTE_NOT_PROJECT 等已统一提示
    } finally {
      setPmSaving(false);
    }
  };

  // 转开发实现：开发负责人由评分规则统一配置，避免每条需求临时选人偏离组织分工。
  const [devOpen, setDevOpen] = useState(false);
  const [devSaving, setDevSaving] = useState(false);
  const configuredDevLeader = memberOptions.find((member) => member.value === config?.review_assignees?.dev_leader);

  const submitToDev = async () => {
    setDevSaving(true);
    try {
      await api.post(`/requirements/${id}/to-dev`, {});
      message.success(t('req.solution.toDevDone'));
      setDevOpen(false);
      onSaved();
    } catch {
      // 已统一提示
    } finally {
      setDevSaving(false);
    }
  };

  return (
    <>
      <Typography.Text strong>{t('req.solution.section')}</Typography.Text>
      <Descriptions column={2} size="small" bordered style={{ margin: '8px 0 16px' }}>
        <Descriptions.Item label={t('req.solution.type')}>
          {editable ? (
            <Radio.Group
              value={detail.solution_type ?? undefined}
              options={SOLUTION_TYPES.map((v) => ({ value: v, label: et.solutionType(v) }))}
              onChange={(e) => void onPatch({ solution_type: e.target.value })}
            />
          ) : (
            et.solutionType(detail.solution_type) || '-'
          )}
        </Descriptions.Item>
        <Descriptions.Item label={t('req.devEffort')}>
          {editable ? (
            <InputNumber
              min={0}
              precision={1}
              style={{ width: 120 }}
              value={devEffort ?? undefined}
              onChange={(v) => setDevEffort((v as number | null) ?? null)}
              onBlur={() => {
                if (devEffort !== (detail.dev_effort ?? null)) void onPatch({ dev_effort: devEffort });
              }}
            />
          ) : detail.dev_effort != null ? (
            t('req.effortDays', { n: detail.dev_effort })
          ) : (
            '-'
          )}
        </Descriptions.Item>
        <Descriptions.Item label={t('req.col.route')} span={2}>
          <Space direction="vertical" size={8}>
            <Space size={8} wrap>
              <RouteTag value={route} />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {basis}
              </Typography.Text>
            </Space>
            {route === ROUTE_PROJECT && isAnalyzing && canOperate && (
              <Button
                type="primary"
                onClick={() => {
                  pmForm.resetFields();
                  setPmOpen(true);
                }}
              >
                {t('req.solution.toProject')}
              </Button>
            )}
            {route === ROUTE_DEV && isAnalyzing && canOperate && (
              <Space size={8} wrap>
                <Button
                  type="primary"
                  onClick={() => {
                    setDevOpen(true);
                  }}
                >
                  {t('req.solution.toDev')}
                </Button>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {t('req.solution.devHint')}
                </Typography.Text>
              </Space>
            )}
          </Space>
        </Descriptions.Item>
      </Descriptions>

      {/* 转项目管理：选项目经理 */}
      <Modal
        title={t('req.solution.toProject')}
        open={pmOpen}
        onOk={() => void submitToProject()}
        confirmLoading={pmSaving}
        onCancel={() => setPmOpen(false)}
        destroyOnClose
      >
        <Alert type="info" showIcon style={{ marginBottom: 16 }} message={t('req.solution.toProjectHint')} />
        <Form form={pmForm} layout="vertical" preserve={false}>
          <Form.Item
            name="pm_id"
            label={t('req.solution.pm')}
            rules={[{ required: true, message: t('req.solution.pmRequired') }]}
          >
            <Select showSearch optionFilterProp="label" placeholder={t('req.selectMember')} options={memberOptions} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 转开发实现：展示评分规则中的固定开发负责人 */}
      <Modal
        title={t('req.solution.toDev')}
        open={devOpen}
        onOk={() => void submitToDev()}
        confirmLoading={devSaving}
        onCancel={() => setDevOpen(false)}
        destroyOnClose
      >
        <Alert type="info" showIcon style={{ marginBottom: 16 }} message={t('req.solution.toDevHint')} />
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label={t('req.solution.devOwner')}>
            {configuredDevLeader?.label || t('req.solution.devOwnerNotConfigured')}
          </Descriptions.Item>
        </Descriptions>
      </Modal>
    </>
  );
}

/** 实际工天行内编辑：本地态输入、失焦提交（未变更不提交），只读时纯展示 */
function ActualEffortCell({
  task,
  editable,
  onSave,
}: {
  task: RequirementTask;
  editable: boolean;
  onSave: (v: number | null) => void;
}) {
  const [val, setVal] = useState<number | null>(task.actual_effort ?? null);
  useEffect(() => {
    setVal(task.actual_effort ?? null);
  }, [task.actual_effort]);
  if (!editable) return <>{task.actual_effort ?? '-'}</>;
  return (
    <InputNumber
      size="small"
      min={0}
      precision={1}
      style={{ width: 72 }}
      value={val ?? undefined}
      onChange={(v) => setVal((v as number | null) ?? null)}
      onBlur={() => {
        if (val !== (task.actual_effort ?? null)) onSave(val);
      }}
    />
  );
}

export default function RequirementDetail() {
  const t = useT();
  const et = useEnums();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const goBack = useGoBack();
  const user = useAuthStore((s) => s.user);
  const { roleLabel } = useRoleOptions();
  const MOSCOW_OPTIONS = MOSCOW_KEYS.map((k) => ({ value: k, label: et.moscow(k) }));

  const [detail, setDetail] = useState<RequirementDetailData | null>(null);
  const [attachments, setAttachments] = useState<AttachmentItem[]>([]);
  const [attachmentUploading, setAttachmentUploading] = useState(false);
  const [resubmitting, setResubmitting] = useState(false);
  const [loading, setLoading] = useState(true);
  const [members, setMembers] = useState<Member[]>([]);
  const [projects, setProjects] = useState<ProjectRow[]>([]);

  // ---------- 加载 ----------
  const load = useCallback(async () => {
    if (!id) return;
    try {
      setDetail(await api.get<RequirementDetailData>(`/requirements/${id}`));
      const attachmentResult = await api
        .getList<AttachmentItem>('/attachments', { entity_type: 'requirement', entity_id: id })
        .catch(() => ({ items: [], total: 0 }));
      setAttachments(attachmentResult.items);
    } catch {
      // 已统一提示
    }
  }, [id]);

  useEffect(() => {
    setLoading(true);
    void load().finally(() => setLoading(false));
  }, [load]);
  useProcessTaskView(detail?.process, user, load);

  // 单据编辑与开发任务维护是两套权限：流程当前节点只读时，任务维护人仍需加载负责人候选。
  const canEdit = detail?.can_edit ?? false;
  const canManageTasks = detail?.can_manage_tasks ?? canEdit;
  const canLoadTaskMembers = shouldLoadRequirementTaskMembers(canEdit, canManageTasks);
  const [completingStep, setCompletingStep] = useState<FlowDiagramStep | null>(null);
  // M28 主动关闭（登记人/admin）
  const [closeOpen, setCloseOpen] = useState(false);
  const [closeReason, setCloseReason] = useState('');
  const [closeReqSaving, setCloseReqSaving] = useState(false);
  /** 示例数据只读：兜底隐藏 can_edit 覆盖不到的写入口（任务负责人路径/转出按钮） */
  const isExample = detail?.is_example === true;
  useEffect(() => {
    if (!canLoadTaskMembers) {
      setMembers([]);
      return;
    }
    api
      .getList<Member>('/members', { page: 1, page_size: 2000, scope: 'it' })
      .then((res) => setMembers(res.items))
      .catch(() => undefined);
  }, [canLoadTaskMembers]);

  useEffect(() => {
    if (!canEdit) {
      setProjects([]);
      return;
    }
    api
      .getList<ProjectRow>('/projects', { page: 1, page_size: 200 })
      .then((res) => setProjects(res.items))
      .catch(() => undefined);
  }, [canEdit]);

  const memberOptions = useMemo(
    () =>
      members.map((m) => ({
        value: m.id,
        label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
      })),
    [members],
  );

  const projectOptions = useMemo(
    () => projects.map((p) => ({ value: p.id, label: `${p.project_code} ${p.name}` })),
    [projects],
  );

  // ---------- 通用 PATCH ----------
  const patchField = async (patch: Record<string, unknown>, okMsg = t('req.saved')) => {
    try {
      await api.patch(`/requirements/${id}`, patch);
      message.success(okMsg);
      void load();
    } catch {
      // 已统一提示
    }
  };

  const uploadSupplementAttachment = async (file: File) => {
    if (!id) return;
    setAttachmentUploading(true);
    try {
      await api.upload<AttachmentItem>(`/attachments?entity_type=requirement&entity_id=${id}`, file);
      message.success(t('req.attachmentUploaded'));
      void load();
    } catch {
      // 已统一提示
    } finally {
      setAttachmentUploading(false);
    }
  };

  const resubmitRequirement = async () => {
    setResubmitting(true);
    try {
      await api.post(`/requirements/${id}/resubmit`, {});
      message.success(t('req.resubmitDone'));
      void load();
    } catch {
      // 已统一提示
    } finally {
      setResubmitting(false);
    }
  };

  // ---------- 状态流转 ----------
  const [closeTrans, setCloseTrans] = useState<AllowedTransition | null>(null);
  const [closeSaving, setCloseSaving] = useState(false);
  const [closeForm] = Form.useForm();

  const runTransition = (tr: AllowedTransition) => {
    if (!detail) return;
    if (tr.to === 'closed') {
      closeForm.setFieldsValue({ closure_note: detail.closure_note ?? undefined });
      setCloseTrans(tr);
      return;
    }
    const needAnalysis = tr.to === 'implementing' && (!detail.moscow || !detail.owner);
    Modal.confirm({
      title: t('req.confirmTransitionTitle', { name: tr.to_name }),
      content: needAnalysis
        ? t('req.needAnalysisHint')
        : t('req.confirmTransitionContent', { name: tr.to_name }),
      onOk: async () => {
        await api.post(`/requirements/${id}/transition`, { to: tr.to, fields: {} });
        message.success(t('req.actionOk'));
        void load();
      },
    });
  };

  const submitClose = async () => {
    const v = await closeForm.validateFields();
    setCloseSaving(true);
    try {
      await api.post(`/requirements/${id}/transition`, {
        to: 'closed',
        fields: v.closure_note ? { closure_note: v.closure_note } : {},
      });
      message.success(t('req.closed'));
      setCloseTrans(null);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setCloseSaving(false);
    }
  };

  // ---------- 编辑基本信息 ----------
  const [editOpen, setEditOpen] = useState(false);
  const [editSaving, setEditSaving] = useState(false);
  const [editForm] = Form.useForm();
  const [domains, setDomains] = useState<BusinessDomain[]>([]);
  const [sources, setSources] = useState<MasterDataItem[]>([]);

  const openEdit = () => {
    if (!detail) return;
    editForm.setFieldsValue({
      title: detail.title,
      req_type: detail.req_type,
      business_domain_id: detail.business_domain_id,
      source: detail.source ?? undefined,
      description: detail.description,
      remarks: detail.remarks ?? undefined,
      expected_date: detail.expected_date ? dayjs(detail.expected_date) : undefined,
      expected_effect: detail.expected_effect ?? undefined,
      business_value_note: detail.business_value_note ?? undefined,
      prd_effort: detail.prd_effort ?? undefined,
      dev_effort: detail.dev_effort ?? undefined,
    });
    setEditOpen(true);
    if (domains.length === 0) {
      api
        .getList<BusinessDomain>('/admin/business-domains')
        .then((res) => setDomains(res.items.filter((d) => d.active)))
        .catch(() => undefined);
    }
    if (sources.length === 0) {
      api
        .getList<MasterDataItem>('/admin/master-data', {
          category: 'requirement_source',
          page: 1,
          page_size: 999,
        })
        .then((res) => setSources(res.items.filter((s) => s.active !== false)))
        .catch(() => undefined);
    }
  };

  const submitEdit = async () => {
    const v = await editForm.validateFields();
    const isUpstreamCorrection = detail?.workflow_edit_mode?.startsWith('upstream_') === true
      || detail?.workflow_edit_mode === 'returned_requester';
    setEditSaving(true);
    try {
      await api.patch(`/requirements/${id}`, {
        title: v.title,
        req_type: v.req_type,
        source: v.source ?? null,
        description: v.description,
        remarks: v.remarks || null,
        expected_date: v.expected_date ? (v.expected_date as Dayjs).format('YYYY-MM-DD') : null,
        expected_effect: v.expected_effect || null,
        business_value_note: v.business_value_note || null,
        prd_effort: v.prd_effort ?? null,
        dev_effort: v.dev_effort ?? null,
        // 上游回改不可更改业务域，避免改变下一节点的责任归属与流程路由。
        ...(isUpstreamCorrection ? {} : { business_domain_id: v.business_domain_id }),
      });
      message.success(t('req.basicUpdated'));
      setEditOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setEditSaving(false);
    }
  };

  // ---------- 验收标准（全量 PATCH） ----------
  const [newCriterion, setNewCriterion] = useState('');

  const saveCriteria = async (list: AcceptanceCriterion[], okMsg: string) => {
    await patchField({ acceptance_criteria: list }, okMsg);
  };

  const addCriterion = () => {
    if (!detail) return;
    const text = newCriterion.trim();
    if (!text) return;
    setNewCriterion('');
    void saveCriteria([...(detail.acceptance_criteria ?? []), { text, checked: false }], t('req.criterionAdded'));
  };

  // ---------- 实现阶段：任务 ----------
  const [taskOpen, setTaskOpen] = useState(false);
  const [taskSaving, setTaskSaving] = useState(false);
  const [taskForm] = Form.useForm();

  const submitTask = async () => {
    const v = await taskForm.validateFields();
    setTaskSaving(true);
    try {
      await api.post(`/requirements/${id}/tasks`, {
        name: v.name,
        description: v.description || null,
        assignee: v.assignee,
        plan_date: v.plan_date ? (v.plan_date as Dayjs).format('YYYY-MM-DD') : null,
        plan_effort: v.plan_effort ?? null,
      });
      message.success(t('req.taskAdded'));
      setTaskOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setTaskSaving(false);
    }
  };

  const changeTaskStatus = async (task: RequirementTask, status: RequirementTaskStatus) => {
    try {
      await api.patch(`/requirements/tasks/${task.id}`, { status });
      message.success(t('req.taskStatusUpdated'));
      void load();
    } catch {
      // 403 等由拦截器统一中文提示
    }
  };

  const deleteTask = async (task: RequirementTask) => {
    try {
      await api.delete(`/requirements/tasks/${task.id}`);
      message.success(t('req.taskDeleted'));
      void load();
    } catch {
      // 已统一提示
    }
  };

  const updateTaskActual = async (task: RequirementTask, actual_effort: number | null) => {
    try {
      await api.patch(`/requirements/tasks/${task.id}`, { actual_effort });
      message.success(t('req.saved'));
      void load();
    } catch {
      // 已统一提示
    }
  };

  // ---------- 关闭收尾：转出 ----------
  const [problemOpen, setProblemOpen] = useState(false);
  const [problemSaving, setProblemSaving] = useState(false);
  const [problemForm] = Form.useForm();

  const submitProblem = async () => {
    const v = await problemForm.validateFields();
    setProblemSaving(true);
    try {
      const res = await api.post<{ problem_id: string; problem_code: string }>(
        `/requirements/${id}/to-problem`,
        { title: v.title || null, description: v.description },
      );
      setProblemOpen(false);
      void load();
      Modal.confirm({
        title: t('req.problemHandoverTitle', { code: res.problem_code }),
        content: t('req.problemHandoverContent'),
        okText: t('req.gotoProblem'),
        cancelText: t('req.stayHere'),
        onOk: () => navigate(`/itsm/problems/${res.problem_id}`),
      });
    } catch {
      // 已统一提示
    } finally {
      setProblemSaving(false);
    }
  };

  const runToKnowledge = () => {
    Modal.confirm({
      title: t('req.toKnowledgeTitle'),
      content: t('req.toKnowledgeContent'),
      onOk: async () => {
        const res = await api.post<{ article_id: string; article_code: string }>(
          `/requirements/${id}/to-knowledge`,
        );
        message.success(t('req.knowledgeCreated', { code: res.article_code }));
        navigate(`/itsm/knowledge/${res.article_id}`);
      },
    });
  };

  // ---------- 渲染 ----------
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
        <Typography.Text type="secondary">{t('req.notFound')}</Typography.Text>
      </Card>
    );
  }

  const st = detail.status;
  const isFinal = st === 'closed' || st === 'cancelled';
  const canCreateLinkedProject = !isExample && !isFinal && !!user && !isRequesterOnly(user);
  /** PATCH 类编辑：终态（closed/cancelled）后端拒绝，一律只读 */
  const canEditNow = canEdit && !isFinal;
  const processRunning = detail.process?.status === 'running';
  const currentProcessStep = processRunning
    ? detail.process?.steps?.find((s) => s.seq === detail.process?.current_step_seq)
    : undefined;
  // 流程实例的当前待处理节点优先于历史阶段时间戳。旧单据可能存在
  // Requirement.status 落后于流程任务的情况，不能再用它决定页面当前阶段。
  const processSeq = detail.process?.current_step_seq ?? null;
  const processCompleted = detail.process?.status === 'completed';
  const processDriven = processRunning && processSeq != null;
  const evaluationIsCurrent = processDriven
    ? !processCompleted && processSeq === 1
    : st === 'registered' || st === 'evaluating';
  const reachedEvaluating = processDriven
    ? processSeq >= 1
    : !!detail.evaluating_at || ['evaluating', 'analyzing', 'implementing', 'closed'].includes(st);
  const reachedAnalyzing = processDriven
    ? processSeq >= 2
    : !!detail.analyzing_at || ['analyzing', 'implementing', 'closed'].includes(st);
  const reachedImplementing = processDriven
    ? processSeq >= 3
    : !!detail.implementing_at || ['implementing', 'closed'].includes(st);
  const showClosure = processDriven
    ? processSeq >= 3
    : st === 'implementing' || st === 'closed';
  const analysisIsCurrent = processDriven ? !processCompleted && processSeq === 2 : st === 'analyzing';

  const criteria = detail.acceptance_criteria ?? [];
  const checkedCount = criteria.filter((c) => c.checked).length;
  const pendingAcceptance = criteria.length - checkedCount;

  const canChangeTaskStatus = (t: RequirementTask): boolean =>
    !isExample && !isFinal && (canManageTasks || (!!user?.person_id && user.person_id === t.assignee));

  // ----- 阶段进度条 -----
  const currentStep = processCompleted || st === 'closed'
    ? 4
    : st === 'supplementing'
      ? 0
    : processDriven
      ? Math.min(4, Math.max(1, processSeq ?? 1))
    : reachedImplementing
      ? 3
      : reachedAnalyzing
        ? 2
        : reachedEvaluating
          ? 1
          : 0;
  const stepItems = [
    { title: t('req.step.register'), description: fmtDt(detail.registered_at) },
    { title: t('req.step.evaluate'), description: fmtDt(detail.evaluating_at) },
    { title: t('req.step.analyze'), description: fmtDt(detail.analyzing_at) },
    { title: t('req.step.implement'), description: fmtDt(detail.implementing_at) },
    {
      title: t('req.step.close'),
      description: detail.closed_at ? (
        <>
          {fmtDt(detail.closed_at)}
          {detail.lead_days != null && <div>{t('req.leadDaysN', { n: detail.lead_days })}</div>}
        </>
      ) : undefined,
    },
  ];

  // ----- 任务表 -----
  const taskColumns: ColumnsType<RequirementTask> = [
    { title: t('req.task.col.name'), dataIndex: 'name', width: 180, ellipsis: true },
    {
      title: t('req.task.desc'),
      dataIndex: 'description',
      width: 200,
      ellipsis: true,
      render: (v: string | null | undefined) =>
        v ? (
          <Tooltip title={v}>
            <span>{v}</span>
          </Tooltip>
        ) : (
          '-'
        ),
    },
    { title: t('req.task.col.assignee'), dataIndex: 'assignee_name', width: 110, render: (v) => v || '-' },
    { title: t('req.task.col.planDate'), dataIndex: 'plan_date', width: 110, onCell: () => ({ className: 'cell-nowrap' }), render: (v) => v || '-' },
    {
      title: t('req.task.effort'),
      key: 'effort',
      width: 170,
      render: (_: unknown, r: RequirementTask) => (
        <Space direction="vertical" size={0}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {t('req.task.planEffort')}: {r.plan_effort ?? '-'}
          </Typography.Text>
          <Space size={4}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {t('req.task.actualEffort')}:
            </Typography.Text>
            <ActualEffortCell
              task={r}
              editable={canChangeTaskStatus(r)}
              onSave={(v) => void updateTaskActual(r, v)}
            />
          </Space>
        </Space>
      ),
    },
    {
      title: t('common.status'),
      dataIndex: 'status',
      width: 110,
      render: (v: RequirementTaskStatus, r) =>
        canChangeTaskStatus(r) ? (
          <Select
            size="small"
            value={v}
            style={{ width: 96 }}
            options={REQ_TASK_STATUSES.map((s) => ({ value: s, label: et.reqTaskStatus(s) }))}
            onChange={(s) => void changeTaskStatus(r, s)}
          />
        ) : (
          <Tag color={REQ_TASK_STATUS_COLORS[v]}>{et.reqTaskStatus(v)}</Tag>
        ),
    },
    { title: t('req.task.col.doneAt'), dataIndex: 'done_at', width: 150, onCell: () => ({ className: 'cell-nowrap' }), render: (v) => fmtDt(v) ?? '-' },
    ...(detail.tasks.some((task) => task.can_delete)
      ? [
          {
            title: t('common.actions'),
            key: 'action',
            width: 80,
            render: (_: unknown, r: RequirementTask) => r.can_delete ? (
              <Popconfirm title={t('req.confirmDeleteTask')} onConfirm={() => void deleteTask(r)}>
                <Button type="link" size="small" danger>
                  {t('common.delete')}
                </Button>
              </Popconfirm>
            ) : '-',
          } as ColumnsType<RequirementTask>[number],
        ]
      : []),
  ];

  const handoverEmpty = detail.handover.problems.length + detail.handover.articles.length === 0;

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {isExample && <ExampleAlert />}
      <DocumentTypeHint documentType="requirement" />
      {/* 头部 */}
      <Card>
        <Space style={{ width: '100%', justifyContent: 'space-between', flexWrap: 'wrap' }}>
          <Space size="middle" wrap>
            <Button icon={<ArrowLeftOutlined />} onClick={() => goBack('/requirements/overview')}>
              {t('req.back')}
            </Button>
            <Typography.Title level={4} style={{ margin: 0 }}>
              {detail.requirement_code} · {detail.title}
            </Typography.Title>
            <ReqStatusBadge status={detail.status} name={detail.status_name} />
            <MoscowTag value={detail.moscow} empty={null} />
          </Space>
          {canCreateLinkedProject && id && (
            <RecordRelationCreateButton
              sourceEntityType="requirement"
              sourceId={id}
              relationType="converted_to_project"
              onCreated={() => void load()}
            />
          )}
          {canEdit && (
            <Space wrap>
              {detail.can_close && (
                <Button
                  danger
                  onClick={() => {
                    setCloseReason('');
                    setCloseOpen(true);
                  }}
                >
                  {t('req.closeTitle')}
                </Button>
              )}
              {(detail.allowed_transitions ?? []).map((tr) => {
                const closeBlocked = tr.to === 'closed' && pendingAcceptance > 0;
                const btn = (
                  <Button
                    type={tr.to === 'cancelled' || tr.to === 'on_hold' ? 'default' : 'primary'}
                    danger={tr.to === 'cancelled'}
                    disabled={closeBlocked}
                    style={closeBlocked ? { pointerEvents: 'none' } : undefined}
                    onClick={() => runTransition(tr)}
                  >
                    {tr.to_name}
                  </Button>
                );
                return closeBlocked ? (
                  <Tooltip key={tr.to} title={t('req.closeBlockedTip', { n: pendingAcceptance })}>
                    <span style={{ cursor: 'not-allowed' }}>{btn}</span>
                  </Tooltip>
                ) : (
                  <span key={tr.to}>{btn}</span>
                );
              })}
            </Space>
          )}
          <ProcessActionButtons
            step={currentProcessStep}
            returnTargets={detail.process?.return_targets}
            disabled={isExample}
            onDone={() => void load()}
          />
        </Space>
      </Card>

      {/* 非常规状态说明 */}
      {st === 'on_hold' && (
        <Alert
          type="warning"
          showIcon
          message={t('req.onHoldTitle')}
          description={t('req.onHoldDesc')}
        />
      )}
      {st === 'cancelled' && (
        <Alert type="info" showIcon message={t('req.cancelledTitle')} description={t('req.cancelledDesc')} />
      )}
      {st === 'supplementing' && (
        <Alert
          type="warning"
          showIcon
          message={t('req.returnedTitle')}
          description={(
            <Space direction="vertical" size={4}>
              <Typography.Text>
                {detail.process?.return_info?.reason || t('req.returnedReasonUnknown')}
              </Typography.Text>
              {detail.process?.return_info?.returned_by_name && (
                <Typography.Text type="secondary">
                  {t('req.returnedBy', { name: detail.process.return_info.returned_by_name })}
                </Typography.Text>
              )}
              {detail.can_resubmit && (
                <Button type="primary" loading={resubmitting} onClick={() => void resubmitRequirement()}>
                  {t('req.resubmit')}
                </Button>
              )}
            </Space>
          )}
        />
      )}

      {/* 阶段进度条 */}
      <Card size="small">
        <Steps
          size="small"
          current={currentStep}
          status={st === 'closed' ? 'finish' : st === 'cancelled' ? 'error' : 'process'}
          items={stepItems}
        />
      </Card>

      {/* 流程示意 */}
      {detail.process && detail.process.steps?.length > 0 && (
        <Card title={t('req.flowTitle', { name: detail.process.definition_name })} size="small">
          <FlowDiagram
            steps={detail.process.steps}
            roleLabel={roleLabel}
            currentSeq={processRunning ? detail.process.current_step_seq : null}
            // M18：能否完成由 FlowDiagram 按任务处理人判定（PM 无需求编辑权也要能完成「实现交付」）
            onCompleteStep={!detail.is_example ? setCompletingStep : undefined}
          />
        </Card>
      )}
      <CompleteStepModal
        step={completingStep}
        onClose={() => setCompletingStep(null)}
        onDone={() => void load()}
      />

      {/* 登记信息 */}
      <Card
        title={t('req.registrationInfo')}
        size="small"
        extra={
          canEditNow && (
            <Button size="small" icon={<EditOutlined />} onClick={openEdit}>
              {t('req.editBasic')}
            </Button>
          )
        }
      >
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label={t('req.col.code')} contentStyle={{ whiteSpace: 'nowrap' }}>{detail.requirement_code}</Descriptions.Item>
          <Descriptions.Item label={t('req.col.type')}>
            <Tag>{et.reqType(detail.req_type)}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label={t('req.col.domain')}>{detail.business_domain_name ?? '-'}</Descriptions.Item>
          <Descriptions.Item label={t('req.source')}>{detail.source || '-'}</Descriptions.Item>
          <Descriptions.Item label={t('req.requester')}>{detail.requester_name ?? '-'}</Descriptions.Item>
          <Descriptions.Item label={t('req.registeredAt')} contentStyle={{ whiteSpace: 'nowrap' }}>{fmtDt(detail.registered_at) ?? '-'}</Descriptions.Item>
          <Descriptions.Item label={t('req.department')}>{detail.department || '-'}</Descriptions.Item>
          <Descriptions.Item label={t('req.expectedDate')} contentStyle={{ whiteSpace: 'nowrap' }}>{detail.expected_date || '-'}</Descriptions.Item>
          <Descriptions.Item label={t('req.prdEffort')}>
            {detail.prd_effort != null ? t('req.effortDays', { n: detail.prd_effort }) : '-'}
          </Descriptions.Item>
          <Descriptions.Item label={t('req.devEffort')}>
            {detail.dev_effort != null ? t('req.effortDays', { n: detail.dev_effort }) : '-'}
          </Descriptions.Item>
          {detail.expected_effect && (
            <Descriptions.Item label={t('req.expectedEffect')} span={2}>
              <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                {detail.expected_effect}
              </Typography.Paragraph>
            </Descriptions.Item>
          )}
          {detail.business_value_note && (
            <Descriptions.Item label={t('req.businessValue')} span={2}>
              <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                {detail.business_value_note}
              </Typography.Paragraph>
            </Descriptions.Item>
          )}
          <Descriptions.Item label={t('req.desc')} span={2}>
            <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
              {detail.description || '-'}
            </Typography.Paragraph>
          </Descriptions.Item>
          {detail.remarks && (
            <Descriptions.Item label={t('req.otherInfo')} span={2}>
              <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                {detail.remarks}
              </Typography.Paragraph>
            </Descriptions.Item>
          )}
        </Descriptions>
      </Card>

      <Card title={t('req.attachments')} size="small">
        {detail.can_resubmit && (
          <Upload
            multiple
            showUploadList={false}
            beforeUpload={(file) => {
              void uploadSupplementAttachment(file);
              return Upload.LIST_IGNORE;
            }}
            accept=".png,.jpg,.jpeg,.gif,.webp,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv"
          >
            <Button
              icon={<PaperClipOutlined />}
              loading={attachmentUploading}
              style={{ marginBottom: attachments.length > 0 ? 12 : 0 }}
            >
              {t('req.uploadSupplementAttachment')}
            </Button>
          </Upload>
        )}
        {attachments.length === 0 ? (
          <Typography.Text type="secondary">{t('req.noAttachments')}</Typography.Text>
        ) : (
          <Space wrap size={[8, 8]}>
            {attachments.map((attachment) => (
              <Button
                key={attachment.id}
                icon={<PaperClipOutlined />}
                onClick={() => void api.download(`/attachments/${attachment.id}/download`)}
              >
                {attachment.filename} ({Math.max(1, Math.ceil(attachment.size / 1024))} KB)
              </Button>
            ))}
          </Space>
        )}
      </Card>

      {/* 评估评分（登记/评估阶段或已有评分时显示） */}
      {id && (evaluationIsCurrent || (detail.scores?.length ?? 0) > 0 || detail.weighted_total != null) && (
        <EvaluationPanel
          id={id}
          detail={detail}
          editable={canEditNow && evaluationIsCurrent}
          onSaved={() => void load()}
        />
      )}

      {/* 分析（进入分析阶段后显示；M16 顶部融入方案评估小节） */}
      {reachedAnalyzing && (
        <Card title={t('req.analysis')} size="small">
          {id && (
            <SolutionEvalSection
              id={id}
              detail={detail}
              editable={canEditNow && analysisIsCurrent}
              isAnalyzing={analysisIsCurrent}
              canOperate={canEdit && !isExample}
              memberOptions={memberOptions}
              onPatch={patchField}
              onSaved={() => void load()}
            />
          )}
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label={t('req.moscowPriority')}>
              {canEditNow ? (
                <Select
                  allowClear
                  placeholder={t('req.notAssessed')}
                  value={detail.moscow ?? undefined}
                  style={{ width: 150 }}
                  options={MOSCOW_OPTIONS}
                  onChange={(v) => void patchField({ moscow: v ?? null }, t('req.priorityUpdated'))}
                />
              ) : (
                <MoscowTag value={detail.moscow} empty={t('req.notAssessed')} />
              )}
            </Descriptions.Item>
            <Descriptions.Item label={t('req.owner')}>
              {canEditNow ? (
                <Select
                  allowClear
                  showSearch
                  placeholder={t('req.unassigned')}
                  optionFilterProp="label"
                  value={detail.owner ?? undefined}
                  style={{ minWidth: 180 }}
                  options={memberOptions}
                  onChange={(v) => void patchField({ owner: v ?? null }, t('req.ownerUpdated'))}
                />
              ) : (
                detail.owner_name || '-'
              )}
            </Descriptions.Item>
            <Descriptions.Item label={t('req.targetDate')}>
              {canEditNow ? (
                <DatePicker
                  value={detail.target_date ? dayjs(detail.target_date) : null}
                  onChange={(d) =>
                    void patchField({ target_date: d ? d.format('YYYY-MM-DD') : null }, t('req.targetDateUpdated'))
                  }
                />
              ) : (
                detail.target_date || '-'
              )}
            </Descriptions.Item>
            <Descriptions.Item label={t('req.solution')} span={2}>
              <Typography.Paragraph
                style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}
                editable={
                  canEditNow
                    ? {
                        text: detail.solution ?? '',
                        autoSize: { minRows: 2 },
                        tooltip: t('req.editSolution'),
                        onChange: (v) => {
                          if (v !== (detail.solution ?? '')) {
                            void patchField({ solution: v || null }, t('req.solutionUpdated'));
                          }
                        },
                      }
                    : false
                }
              >
                {detail.solution || t('req.none')}
              </Typography.Paragraph>
            </Descriptions.Item>
          </Descriptions>

          {/* 验收标准清单 */}
          <div style={{ marginTop: 16 }}>
            <Space style={{ marginBottom: 8 }}>
              <Typography.Text strong>{t('req.acceptanceCriteria')}</Typography.Text>
              {criteria.length > 0 && (
                <Tag color={pendingAcceptance === 0 ? 'green' : 'orange'} style={{ marginInlineEnd: 0 }}>
                  {t('req.passedCount', { done: checkedCount, total: criteria.length })}
                </Tag>
              )}
            </Space>
            {criteria.length === 0 && (
              <div>
                <Typography.Text type="secondary">
                  {canEditNow ? t('req.noCriteriaEditable') : t('req.noCriteria')}
                </Typography.Text>
              </div>
            )}
            {criteria.map((c, i) => (
              <div
                key={`${i}-${c.text}`}
                style={{ display: 'flex', alignItems: 'flex-start', gap: 8, padding: '4px 0' }}
              >
                <Checkbox
                  checked={c.checked}
                  disabled={!canEditNow}
                  onChange={(e) =>
                    void saveCriteria(
                      criteria.map((x, j) => (j === i ? { ...x, checked: e.target.checked } : x)),
                      e.target.checked ? t('req.criterionChecked') : t('req.criterionUnchecked'),
                    )
                  }
                />
                <span style={{ flex: 1, ...(c.checked ? { color: 'rgba(0,0,0,0.45)' } : {}) }}>{c.text}</span>
                {canEditNow && (
                  <Button
                    type="text"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() =>
                      void saveCriteria(
                        criteria.filter((_, j) => j !== i),
                        t('req.criterionDeleted'),
                      )
                    }
                  />
                )}
              </div>
            ))}
            {canEditNow && (
              <Space.Compact style={{ width: '100%', maxWidth: 480, marginTop: 8 }}>
                <Input
                  value={newCriterion}
                  onChange={(e) => setNewCriterion(e.target.value)}
                  placeholder={t('req.criterionPlaceholder')}
                  maxLength={200}
                  onPressEnter={addCriterion}
                />
                <Button icon={<PlusOutlined />} onClick={addCriterion}>
                  {t('req.add')}
                </Button>
              </Space.Compact>
            )}
          </div>
        </Card>
      )}

      {/* 实现（进入实现阶段后显示） */}
      {reachedImplementing && (
        <Card
          title={t('req.implementation')}
          size="small"
          extra={
            canManageTasks && (
              <Button
                size="small"
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => {
                  taskForm.resetFields();
                  setTaskOpen(true);
                }}
              >
                {t('req.addTask')}
              </Button>
            )
          }
        >
          <Descriptions column={2} size="small" bordered style={{ marginBottom: 16 }}>
            <Descriptions.Item label={t('req.linkedProject')}>
              {canEditNow ? (
                <Space wrap>
                  <Select
                    allowClear
                    showSearch
                    placeholder={t('req.linkProjectPlaceholder')}
                    optionFilterProp="label"
                    value={detail.project_id ?? undefined}
                    style={{ minWidth: 240 }}
                    options={projectOptions}
                    onChange={(v) => void patchField({ project_id: v ?? null }, t('req.linkedProjectUpdated'))}
                  />
                  {detail.project_id && <Link to={`/projects/${detail.project_id}`}>{t('req.viewProject')}</Link>}
                  {detail.project_relation_reason && (
                    <Typography.Text type="secondary">{detail.project_relation_reason}</Typography.Text>
                  )}
                </Space>
              ) : detail.project_id ? (
                <Space direction="vertical" size={0}>
                  <Link to={`/projects/${detail.project_id}`}>{detail.project_name || t('req.viewProject')}</Link>
                  {detail.project_relation_reason && (
                    <Typography.Text type="secondary">{detail.project_relation_reason}</Typography.Text>
                  )}
                </Space>
              ) : (
                '-'
              )}
            </Descriptions.Item>
            <Descriptions.Item label={t('req.taskProgress')}>
              {detail.task_total === 0 ? (
                <Typography.Text type="secondary">{t('req.noTask')}</Typography.Text>
              ) : (
                <Progress
                  percent={detail.progress ?? 0}
                  style={{ minWidth: 180, marginBottom: 0 }}
                  format={() => `${detail.task_done}/${detail.task_total}`}
                />
              )}
            </Descriptions.Item>
          </Descriptions>

          <Table<RequirementTask>
            size="small"
            rowKey="id"
            columns={taskColumns}
            dataSource={detail.tasks}
            pagination={false}
            sticky
            scroll={{ x: 'max-content' }}
            locale={{ emptyText: t('req.emptyTasks') }}
          />
        </Card>
      )}

      {/* 关闭收尾（实现中/已关闭显示） */}
      {showClosure && (
        <Card title={t('req.closure')} size="small">
          {canEdit && !isExample && (
            <Space wrap style={{ marginBottom: 16 }}>
              <Button
                icon={<ExportOutlined />}
                onClick={() => {
                  problemForm.resetFields();
                  setProblemOpen(true);
                }}
              >
                {t('req.handoverProblem')}
              </Button>
              <Button icon={<BookOutlined />} onClick={runToKnowledge}>
                {t('req.toKnowledge')}
              </Button>
            </Space>
          )}

          <Typography.Text strong>{t('req.handoverList')}</Typography.Text>
          <div style={{ margin: '8px 0 16px' }}>
            {handoverEmpty ? (
              <Typography.Text type="secondary">{t('req.noHandover')}</Typography.Text>
            ) : (
              <Space direction="vertical" size={4}>
                {detail.handover.problems.map((p) => (
                  <div key={p.id}>
                    <Tag color="volcano">{t('req.tagProblem')}</Tag>
                    <Link to={`/itsm/problems/${p.id}`}>{p.problem_code}</Link>{' '}
                    <Typography.Text>{p.title}</Typography.Text>
                  </div>
                ))}
                {detail.handover.articles.map((a) => (
                  <div key={a.id}>
                    <Tag color="green">{t('req.tagKnowledge')}</Tag>
                    <Link to={`/itsm/knowledge/${a.id}`}>{a.article_code}</Link>{' '}
                    <Typography.Text>{a.title}</Typography.Text>
                  </div>
                ))}
              </Space>
            )}
          </div>

          <Typography.Text strong>{t('req.closureNote')}</Typography.Text>
          <Typography.Paragraph
            style={{ marginTop: 8, marginBottom: 0, whiteSpace: 'pre-wrap' }}
            editable={
              canEditNow
                ? {
                    text: detail.closure_note ?? '',
                    autoSize: { minRows: 2 },
                    tooltip: t('req.editClosureNote'),
                    onChange: (v) => {
                      if (v !== (detail.closure_note ?? '')) {
                        void patchField({ closure_note: v || null }, t('req.closureNoteUpdated'));
                      }
                    },
                  }
                : false
            }
          >
            {detail.closure_note || t('req.none')}
          </Typography.Paragraph>
        </Card>
      )}

      <RecordRelationsPanel
        entityType="requirement"
        entityId={detail.id}
        excludeRelationTypes={['converted_to_project']}
        hideWhenEmpty
      />

      <InvestmentPanel
        subjectType="requirement"
        subjectId={detail.id}
        lifecycleStage="demand"
        readOnly={isExample}
      />

      {/* 编辑基本信息 Modal */}
      <Modal
        title={t('req.editBasic')}
        open={editOpen}
        width={560}
        onOk={() => void submitEdit()}
        confirmLoading={editSaving}
        onCancel={() => setEditOpen(false)}
        destroyOnClose
      >
        <Form form={editForm} layout="vertical">
          <Form.Item
            name="title"
            label={t('req.reqTitle')}
            rules={[
              { required: true, message: t('req.reqTitleRequired') },
              { min: 2, message: t('req.min2') },
            ]}
          >
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="req_type" label={t('req.reqType')} rules={[{ required: true, message: t('req.reqTypeRequired') }]}>
            <Select options={REQ_TYPES.map((v) => ({ value: v, label: et.reqType(v) }))} />
          </Form.Item>
          {!detail?.workflow_edit_mode?.startsWith('upstream_') && detail?.workflow_edit_mode !== 'returned_requester' && (
            <Form.Item
              name="business_domain_id"
              label={t('req.belongDomain')}
              rules={[{ required: true, message: t('req.domainRequired') }]}
            >
              <Select showSearch optionFilterProp="label" options={domains.map((d) => ({ value: d.id, label: d.name }))} />
            </Form.Item>
          )}
          <Form.Item name="source" label={t('req.source')}>
            <Select allowClear options={sources.map((s) => ({ value: s.name, label: s.name }))} />
          </Form.Item>
          <Form.Item name="description" label={t('req.reqDesc')} rules={[{ required: true, message: t('req.reqDescRequired') }]}>
            <Input.TextArea rows={4} maxLength={2000} />
          </Form.Item>
          <Space size={16} wrap style={{ width: '100%' }} align="start">
            <Form.Item name="expected_date" label={t('req.expectedDate')}>
              <DatePicker style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="prd_effort" label={t('req.prdEffort')} style={{ width: 130 }}>
              <InputNumber min={0} precision={1} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="dev_effort" label={t('req.devEffort')} style={{ width: 130 }}>
              <InputNumber min={0} precision={1} style={{ width: '100%' }} />
            </Form.Item>
          </Space>
          <Form.Item name="expected_effect" label={t('req.expectedEffect')}>
            <Input.TextArea rows={2} maxLength={1000} placeholder={t('req.expectedEffectPlaceholder')} />
          </Form.Item>
          <Form.Item name="business_value_note" label={t('req.businessValue')}>
            <Input.TextArea rows={2} maxLength={1000} placeholder={t('req.businessValuePlaceholder')} />
          </Form.Item>
          <Form.Item name="remarks" label={t('common.remark')}>
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 关闭需求 Modal（closure_note 随流转 fields 提交） */}
      <Modal
        title={t('req.closeReqTitle')}
        open={!!closeTrans}
        onOk={() => void submitClose()}
        confirmLoading={closeSaving}
        onCancel={() => setCloseTrans(null)}
        destroyOnClose
      >
        <Alert
          type={criteria.length > 0 ? 'success' : 'info'}
          showIcon
          style={{ marginBottom: 16 }}
          message={
            criteria.length > 0
              ? t('req.allCriteriaPassed', { done: checkedCount, total: criteria.length })
              : t('req.noCriteriaSet')
          }
          description={t('req.closeReqDesc')}
        />
        <Form form={closeForm} layout="vertical">
          <Form.Item name="closure_note" label={t('req.closureNoteOptional')}>
            <Input.TextArea rows={3} maxLength={1000} placeholder={t('req.closureNotePlaceholder')} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 添加任务 Modal */}
      <Modal
        title={t('req.addTask')}
        open={taskOpen}
        onOk={() => void submitTask()}
        confirmLoading={taskSaving}
        onCancel={() => setTaskOpen(false)}
        destroyOnClose
      >
        <Form form={taskForm} layout="vertical" preserve={false}>
          <Form.Item name="name" label={t('req.task.col.name')} rules={[{ required: true, message: t('req.taskNameRequired') }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="description" label={t('req.task.desc')}>
            <Input.TextArea rows={3} maxLength={1000} placeholder={t('req.task.descPlaceholder')} />
          </Form.Item>
          <Form.Item name="assignee" label={t('req.assignee')} rules={[{ required: true, message: t('req.assigneeRequired') }]}>
            <Select showSearch optionFilterProp="label" placeholder={t('req.selectMember')} options={memberOptions} />
          </Form.Item>
          <Space size={16} wrap style={{ width: '100%' }} align="start">
            <Form.Item name="plan_date" label={t('req.task.col.planDate')}>
              <DatePicker style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="plan_effort" label={t('req.task.planEffort')} style={{ width: 140 }}>
              <InputNumber min={0} precision={1} style={{ width: '100%' }} />
            </Form.Item>
          </Space>
        </Form>
      </Modal>

      {/* 转出遗留问题 Modal */}
      <Modal
        title={t('req.handoverProblem')}
        open={problemOpen}
        onOk={() => void submitProblem()}
        confirmLoading={problemSaving}
        onCancel={() => setProblemOpen(false)}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={t('req.handoverProblemHint')}
        />
        <Form form={problemForm} layout="vertical" preserve={false}>
          <Form.Item name="title" label={t('req.problemTitle')} extra={t('req.problemTitleExtra', { title: detail.title })}>
            <Input maxLength={200} placeholder={t('req.optional')} />
          </Form.Item>
          <Form.Item name="description" label={t('req.problemDesc')} rules={[{ required: true, message: t('req.problemDescRequired') }]}>
            <Input.TextArea rows={4} maxLength={2000} placeholder={t('req.problemDescPlaceholder')} />
          </Form.Item>
        </Form>
      </Modal>
          <Modal
        title={`${t('req.closeTitle')} · ${detail.requirement_code}`}
        open={closeOpen}
        confirmLoading={closeReqSaving}
        okButtonProps={{ danger: true }}
        onOk={async () => {
          if (closeReason.trim().length < 5) {
            message.warning(t('req.closeReasonRequired'));
            return;
          }
          setCloseReqSaving(true);
          try {
            await api.post(`/requirements/${id}/close`, { reason: closeReason.trim() });
            message.success(t('req.closedMsg'));
            setCloseOpen(false);
            void load();
          } catch {
            // 已统一提示
          } finally {
            setCloseReqSaving(false);
          }
        }}
        onCancel={() => setCloseOpen(false)}
        destroyOnClose
      >
        <div style={{ marginBottom: 8 }}>{t('req.closeReason')}</div>
        <Input.TextArea rows={3} maxLength={500} value={closeReason} onChange={(e) => setCloseReason(e.target.value)}
          placeholder={t('req.closeReasonPlaceholder')} />
      </Modal>
</Space>
  );
}
