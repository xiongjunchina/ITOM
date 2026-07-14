import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Button,
  DatePicker,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Spin,
  Steps,
  Table,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { FileWordOutlined, InboxOutlined } from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { api } from '../../api/client';
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';
import type { CharterCreateResult, CharterParseResult, Member, RequirementRow, RiskGrade } from '../../api/types';
import { RISK_GRADES } from '../../api/types';
import { fetchLinkableRequirements } from './shared';

interface CharterFormValues {
  name: string;
  pm: string;
  planned: [Dayjs, Dayjs];
  budget_10k?: number;
  description?: string;
}

interface WbsRowState {
  key: number;
  stage?: string | null;
  wbs_code?: string | null;
  name: string;
  wbs_dict?: string | null;
  deliverable?: string | null;
  assignee_name?: string | null;
  is_milestone?: boolean;
  predecessor_codes?: string | null;
  start_date: Dayjs | null;
  end_date: Dayjs | null;
}

interface RiskRowState {
  key: number;
  title: string;
  probability: RiskGrade;
  impact: RiskGrade;
  mitigation?: string | null;
}

interface CharterImportModalProps {
  open: boolean;
  onClose: () => void;
}

const asGrade = (v?: string | null): RiskGrade => (v === '高' || v === '低' ? v : '中');

/**
 * 章程导入向导（两步）：
 * 1) 上传 .docx → 解析 → 字段表单 + warnings + WBS/风险草稿表（可勾选，WBS 名称可行内编辑；里程碑为 WBS is_milestone 行）；
 * 2) 确认 → POST /projects/charter/create → 跳转项目详情。
 */
export default function CharterImportModal({ open, onClose }: CharterImportModalProps) {
  const t = useT();
  const et = useEnums();
  const navigate = useNavigate();
  const [form] = Form.useForm<CharterFormValues>();

  const [step, setStep] = useState(0);
  const [parsing, setParsing] = useState(false);
  const [fileName, setFileName] = useState('');
  const [parsed, setParsed] = useState<CharterParseResult | null>(null);
  const [members, setMembers] = useState<Member[]>([]);

  const [wbsRows, setWbsRows] = useState<WbsRowState[]>([]);
  const [riskRows, setRiskRows] = useState<RiskRowState[]>([]);
  const [wbsKeys, setWbsKeys] = useState<React.Key[]>([]);
  const [riskKeys, setRiskKeys] = useState<React.Key[]>([]);

  // 确认页快照
  const [confirmed, setConfirmed] = useState<CharterFormValues | null>(null);
  const [creating, setCreating] = useState(false);

  // M16 确认页可选关联需求（转项目管理且未挂接项目），提交随 fields.requirement_id 落库
  const [linkableReqs, setLinkableReqs] = useState<RequirementRow[]>([]);
  const [reqId, setReqId] = useState<string | undefined>();

  useEffect(() => {
    if (!open) {
      setStep(0);
      setParsed(null);
      setFileName('');
      setConfirmed(null);
      setWbsRows([]);
      setRiskRows([]);
      setReqId(undefined);
      form.resetFields();
      return;
    }
    if (members.length === 0) {
      api
        .getList<Member>('/members', { page: 1, page_size: 999 })
        .then((res) => setMembers(res.items))
        .catch(() => undefined);
    }
    fetchLinkableRequirements()
      .then(setLinkableReqs)
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const doParse = async (file: File) => {
    setParsing(true);
    try {
      const res = await api.upload<CharterParseResult>('/projects/charter/parse', file);
      setFileName(file.name);
      setParsed(res);
      const f = res.fields;
      form.setFieldsValue({
        name: f.name ?? undefined,
        pm: f.pm ?? undefined,
        planned:
          f.planned_start && f.planned_end
            ? [dayjs(f.planned_start), dayjs(f.planned_end)]
            : undefined,
        budget_10k: f.budget_10k ?? undefined,
        description: f.description ?? undefined,
      });
      const wbs = res.drafts.wbs.map((w, i) => ({
        key: i,
        stage: w.stage,
        wbs_code: w.wbs_code,
        name: w.name ?? '',
        wbs_dict: w.wbs_dict,
        deliverable: w.deliverable,
        assignee_name: w.assignee_name,
        is_milestone: w.is_milestone,
        predecessor_codes: w.predecessor_codes,
        start_date: w.start_date ? dayjs(w.start_date) : null,
        end_date: w.end_date ? dayjs(w.end_date) : null,
      }));
      const risks = res.drafts.risks.map((r, i) => ({
        key: i,
        title: r.title ?? '',
        probability: asGrade(r.probability),
        impact: asGrade(r.impact),
        mitigation: r.mitigation,
      }));
      setWbsRows(wbs);
      setRiskRows(risks);
      setWbsKeys(wbs.map((r) => r.key));
      setRiskKeys(risks.map((r) => r.key));
    } catch {
      // 已统一提示
    } finally {
      setParsing(false);
    }
  };

  const goConfirm = async () => {
    const values = await form.validateFields();
    setConfirmed(values);
    setStep(1);
  };

  const submitCreate = async () => {
    if (!confirmed) return;
    setCreating(true);
    try {
      const res = await api.post<CharterCreateResult>('/projects/charter/create', {
        fields: {
          name: confirmed.name,
          pm: confirmed.pm,
          planned_start: confirmed.planned[0].format('YYYY-MM-DD'),
          planned_end: confirmed.planned[1].format('YYYY-MM-DD'),
          budget_10k: confirmed.budget_10k ?? null,
          description: confirmed.description || null,
          // M16 关联来源需求：项目验收关闭自动闭环该需求
          requirement_id: reqId ?? null,
          // M13 章程信息分段字段：解析结果原样透传落库（本表单不编辑）
          background: parsed?.fields.background ?? null,
          goals: parsed?.fields.goals ?? null,
          scope_in: parsed?.fields.scope_in ?? null,
          scope_out: parsed?.fields.scope_out ?? null,
          resource_note: parsed?.fields.resource_note ?? null,
          org_members: parsed?.fields.org_members ?? [],
          stakeholders: parsed?.fields.stakeholders ?? [],
        },
        wbs: wbsRows
          .filter((r) => wbsKeys.includes(r.key))
          .map((r) => ({
            stage: r.stage ?? null,
            wbs_code: r.wbs_code ?? null,
            name: r.name,
            wbs_dict: r.wbs_dict ?? null,
            deliverable: r.deliverable ?? null,
            assignee_name: r.assignee_name ?? null,
            is_milestone: r.is_milestone ?? false,
            predecessor_codes: r.predecessor_codes ?? null,
            start_date: r.start_date?.format('YYYY-MM-DD') ?? null,
            end_date: r.end_date?.format('YYYY-MM-DD') ?? null,
          })),
        risks: riskRows
          .filter((r) => riskKeys.includes(r.key))
          .map((r) => ({
            title: r.title,
            probability: r.probability,
            impact: r.impact,
            mitigation: r.mitigation,
          })),
      });
      message.success(t('proj.charter.created', { code: res.project_code }));
      onClose();
      navigate(`/projects/${res.project_id}`);
    } catch {
      // 已统一提示
    } finally {
      setCreating(false);
    }
  };

  const fmtDate = (d: Dayjs | null) => (d ? d.format('YYYY-MM-DD') : '-');

  /** M13 章程字段只读预览：截断 2 行，空显示 - */
  const charterPreview = (v?: string | null) => (
    <Typography.Paragraph style={{ marginBottom: 0 }} ellipsis={{ rows: 2 }}>
      {v || '-'}
    </Typography.Paragraph>
  );

  const wbsColumns: ColumnsType<WbsRowState> = [
    { title: t('proj.wbs.col.stage'), dataIndex: 'stage', width: 90, ellipsis: true, render: (v) => v || '-' },
    { title: t('proj.wbs.col.code'), dataIndex: 'wbs_code', width: 80, render: (v) => v || '-' },
    {
      title: t('proj.charter.wbs.col.name'),
      dataIndex: 'name',
      width: 160,
      render: (_, r) => (
        <Input
          size="small"
          value={r.name}
          maxLength={200}
          onChange={(e) =>
            setWbsRows((rows) => rows.map((x) => (x.key === r.key ? { ...x, name: e.target.value } : x)))
          }
        />
      ),
    },
    { title: t('proj.wbs.col.assignee'), dataIndex: 'assignee_name', width: 90, render: (v) => v || '-' },
    {
      title: t('proj.wbs.col.milestone'),
      dataIndex: 'is_milestone',
      width: 70,
      align: 'center',
      render: (v) => (v ? <Tag color="blue">{t('proj.yes')}</Tag> : <Tag>{t('proj.no')}</Tag>),
    },
    { title: t('proj.wbs.col.predecessors'), dataIndex: 'predecessor_codes', width: 90, ellipsis: true, render: (v) => v || '-' },
    { title: t('proj.wbs.col.plannedStart'), dataIndex: 'start_date', width: 110, onCell: () => ({ className: 'cell-nowrap' }), render: (_, r) => fmtDate(r.start_date) },
    { title: t('proj.wbs.col.plannedEnd'), dataIndex: 'end_date', width: 110, onCell: () => ({ className: 'cell-nowrap' }), render: (_, r) => fmtDate(r.end_date) },
    { title: t('proj.deliverable'), dataIndex: 'deliverable', width: 130, ellipsis: true, render: (v) => v || '-' },
  ];

  const riskColumns: ColumnsType<RiskRowState> = [
    {
      title: t('proj.riskTitle'),
      dataIndex: 'title',
      render: (_, r) => (
        <Input
          size="small"
          value={r.title}
          maxLength={200}
          onChange={(e) =>
            setRiskRows((rows) => rows.map((x) => (x.key === r.key ? { ...x, title: e.target.value } : x)))
          }
        />
      ),
    },
    {
      title: t('proj.riskProb'),
      dataIndex: 'probability',
      width: 90,
      render: (_, r) => (
        <Select
          size="small"
          value={r.probability}
          style={{ width: 72 }}
          options={RISK_GRADES.map((g) => ({ value: g, label: et.riskGrade(g) }))}
          onChange={(v) =>
            setRiskRows((rows) => rows.map((x) => (x.key === r.key ? { ...x, probability: v } : x)))
          }
        />
      ),
    },
    {
      title: t('proj.riskImpact'),
      dataIndex: 'impact',
      width: 90,
      render: (_, r) => (
        <Select
          size="small"
          value={r.impact}
          style={{ width: 72 }}
          options={RISK_GRADES.map((g) => ({ value: g, label: et.riskGrade(g) }))}
          onChange={(v) =>
            setRiskRows((rows) => rows.map((x) => (x.key === r.key ? { ...x, impact: v } : x)))
          }
        />
      ),
    },
    { title: t('proj.mitigation'), dataIndex: 'mitigation', ellipsis: true, render: (v) => v || '-' },
  ];

  const memberOptions = members.map((m) => ({
    value: m.id,
    label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
  }));
  const pmLabel = (id?: string) => memberOptions.find((o) => o.value === id)?.label ?? id ?? '-';

  return (
    <Modal
      title={t('proj.charterImport')}
      open={open}
      width={960}
      onCancel={onClose}
      maskClosable={false}
      footer={
        step === 0 ? (
          <Space>
            <Button onClick={onClose}>{t('common.cancel')}</Button>
            <Button type="primary" disabled={!parsed} onClick={() => void goConfirm()}>
              {t('proj.charter.next')}
            </Button>
          </Space>
        ) : (
          <Space>
            <Button onClick={() => setStep(0)}>{t('proj.charter.prev')}</Button>
            <Button type="primary" loading={creating} onClick={() => void submitCreate()}>
              {t('proj.charter.confirmCreate')}
            </Button>
          </Space>
        )
      }
    >
      <Steps
        size="small"
        current={step}
        items={[{ title: t('proj.charter.step1') }, { title: t('proj.charter.step2') }]}
        style={{ marginBottom: 16, maxWidth: 420 }}
      />

      {/* 第一步：上传 + 解析结果编辑（第二步时隐藏而非卸载，保留表单值） */}
      <div style={{ display: step === 0 ? 'block' : 'none' }}>
        {!parsed ? (
          <Spin spinning={parsing} tip={t('proj.charter.parsing')}>
            <Upload.Dragger
              accept=".docx"
              showUploadList={false}
              disabled={parsing}
              beforeUpload={(file) => {
                void doParse(file);
                return false;
              }}
            >
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p className="ant-upload-text">{t('proj.charter.dragText')}</p>
              <p className="ant-upload-hint">{t('proj.charter.dragHint')}</p>
            </Upload.Dragger>
          </Spin>
        ) : (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Space>
              <FileWordOutlined style={{ color: '#1677ff' }} />
              <Typography.Text>{fileName}</Typography.Text>
              <Button size="small" onClick={() => setParsed(null)}>
                {t('proj.charter.reupload')}
              </Button>
            </Space>

            {parsed.warnings.length > 0 && (
              <Alert
                type="warning"
                showIcon
                message={t('proj.charter.parseWarn')}
                description={
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {parsed.warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                }
              />
            )}

            <Form<CharterFormValues> form={form} layout="vertical">
              <Space size={16} wrap style={{ width: '100%' }} align="start">
                <Form.Item
                  name="name"
                  label={t('proj.projectName')}
                  rules={[
                    { required: true, message: t('proj.projectNameRequired') },
                    { min: 2, message: t('proj.min2') },
                  ]}
                  style={{ width: 300, marginBottom: 8 }}
                >
                  <Input maxLength={200} />
                </Form.Item>
                <Form.Item
                  name="pm"
                  label={t('proj.pm')}
                  rules={[{ required: true, message: t('proj.pmRequired') }]}
                  style={{ width: 220, marginBottom: 8 }}
                >
                  <Select showSearch optionFilterProp="label" options={memberOptions} placeholder={t('proj.selectMember')} />
                </Form.Item>
                <Form.Item
                  name="planned"
                  label={t('proj.planned')}
                  rules={[{ required: true, message: t('proj.plannedRequired') }]}
                  style={{ marginBottom: 8 }}
                >
                  <DatePicker.RangePicker />
                </Form.Item>
                <Form.Item name="budget_10k" label={t('proj.budgetWan')} style={{ width: 150, marginBottom: 8 }}>
                  <InputNumber min={0} precision={2} style={{ width: '100%' }} />
                </Form.Item>
              </Space>
              <Form.Item name="description" label={t('proj.charter.projectDesc')} style={{ marginBottom: 8 }}>
                <Input.TextArea rows={3} maxLength={2000} />
              </Form.Item>
            </Form>

            <Typography.Text strong>{t('proj.charter.wbsDraft')}</Typography.Text>
            <Table<WbsRowState>
              size="small"
              rowKey="key"
              columns={wbsColumns}
              dataSource={wbsRows}
              pagination={false}
              scroll={{ x: 'max-content' }}
              rowSelection={{ selectedRowKeys: wbsKeys, onChange: setWbsKeys }}
              locale={{ emptyText: t('proj.charter.emptyWbs') }}
            />
            <Typography.Text strong>{t('proj.charter.riskDraft')}</Typography.Text>
            <Table<RiskRowState>
              size="small"
              rowKey="key"
              columns={riskColumns}
              dataSource={riskRows}
              pagination={false}
              rowSelection={{ selectedRowKeys: riskKeys, onChange: setRiskKeys }}
              locale={{ emptyText: t('proj.charter.emptyRisk') }}
            />
          </Space>
        )}
      </div>

      {/* 第二步：确认 */}
      {step === 1 && confirmed && (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label={t('proj.projectName')}>{confirmed.name}</Descriptions.Item>
            <Descriptions.Item label={t('proj.pm')}>{pmLabel(confirmed.pm)}</Descriptions.Item>
            <Descriptions.Item label={t('proj.planned')} contentStyle={{ whiteSpace: 'nowrap' }}>
              {confirmed.planned[0].format('YYYY-MM-DD')} ~ {confirmed.planned[1].format('YYYY-MM-DD')}
            </Descriptions.Item>
            <Descriptions.Item label={t('proj.budgetWan')}>{confirmed.budget_10k ?? '-'}</Descriptions.Item>
            {/* M13 章程信息只读预览（解析结果透传创建，此处不编辑） */}
            <Descriptions.Item label={t('proj.charter.background')} span={2}>
              {charterPreview(parsed?.fields.background)}
            </Descriptions.Item>
            <Descriptions.Item label={t('proj.charter.goals')} span={2}>
              {charterPreview(parsed?.fields.goals)}
            </Descriptions.Item>
            <Descriptions.Item label={t('proj.charter.scopeIn')}>
              {charterPreview(parsed?.fields.scope_in)}
            </Descriptions.Item>
            <Descriptions.Item label={t('proj.charter.scopeOut')}>
              {charterPreview(parsed?.fields.scope_out)}
            </Descriptions.Item>
            <Descriptions.Item label={t('proj.charter.resourceNote')}>
              {charterPreview(parsed?.fields.resource_note)}
            </Descriptions.Item>
            <Descriptions.Item label={t('proj.charter.org')}>
              {t('proj.charter.orgCount', {
                members: parsed?.fields.org_members?.length ?? 0,
                stakeholders: parsed?.fields.stakeholders?.length ?? 0,
              })}
            </Descriptions.Item>
            <Descriptions.Item label={t('proj.desc')} span={2}>
              <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                {confirmed.description || '-'}
              </Typography.Paragraph>
            </Descriptions.Item>
          </Descriptions>
          {/* M16 关联来源需求（可选） */}
          <div>
            <Typography.Text strong>{t('proj.linkReq')}</Typography.Text>
            <div style={{ margin: '4px 0' }}>
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder={t('proj.linkReqPlaceholder')}
                style={{ width: 480, maxWidth: '100%' }}
                value={reqId}
                onChange={(v) => setReqId(v)}
                options={linkableReqs.map((r) => ({
                  value: r.id,
                  label: `${r.requirement_code} ${r.title}`,
                }))}
              />
            </div>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {t('proj.linkReqHint')}
            </Typography.Text>
          </div>
          <Alert
            type="info"
            showIcon
            message={t('proj.charter.summaryInfo', {
              wbs: wbsKeys.length,
              ms: wbsRows.filter((r) => wbsKeys.includes(r.key) && r.is_milestone).length,
              risk: riskKeys.length,
            })}
            description={t('proj.charter.summaryDesc')}
          />
        </Space>
      )}
    </Modal>
  );
}
