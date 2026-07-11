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
  Typography,
  Upload,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { FileWordOutlined, InboxOutlined } from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { api } from '../../api/client';
import type { CharterCreateResult, CharterParseResult, Member, RiskGrade } from '../../api/types';
import { RISK_GRADES } from '../../api/types';

interface CharterFormValues {
  name: string;
  pm: string;
  planned: [Dayjs, Dayjs];
  budget_10k?: number;
  description?: string;
}

interface WbsRowState {
  key: number;
  code?: string | null;
  name: string;
  description?: string | null;
  deliverable?: string | null;
  end_date: Dayjs | null;
}

interface MsRowState {
  key: number;
  name: string;
  target_date: Dayjs | null;
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
 * 1) 上传 .docx → 解析 → 字段表单 + warnings + WBS/里程碑/风险草稿表（可勾选、可行内编辑名称与日期）；
 * 2) 确认 → POST /projects/charter/create → 跳转项目详情。
 */
export default function CharterImportModal({ open, onClose }: CharterImportModalProps) {
  const navigate = useNavigate();
  const [form] = Form.useForm<CharterFormValues>();

  const [step, setStep] = useState(0);
  const [parsing, setParsing] = useState(false);
  const [fileName, setFileName] = useState('');
  const [parsed, setParsed] = useState<CharterParseResult | null>(null);
  const [members, setMembers] = useState<Member[]>([]);

  const [wbsRows, setWbsRows] = useState<WbsRowState[]>([]);
  const [msRows, setMsRows] = useState<MsRowState[]>([]);
  const [riskRows, setRiskRows] = useState<RiskRowState[]>([]);
  const [wbsKeys, setWbsKeys] = useState<React.Key[]>([]);
  const [msKeys, setMsKeys] = useState<React.Key[]>([]);
  const [riskKeys, setRiskKeys] = useState<React.Key[]>([]);

  // 确认页快照
  const [confirmed, setConfirmed] = useState<CharterFormValues | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (!open) {
      setStep(0);
      setParsed(null);
      setFileName('');
      setConfirmed(null);
      setWbsRows([]);
      setMsRows([]);
      setRiskRows([]);
      form.resetFields();
      return;
    }
    if (members.length === 0) {
      api
        .getList<Member>('/members', { page: 1, page_size: 999 })
        .then((res) => setMembers(res.items))
        .catch(() => undefined);
    }
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
        code: w.code,
        name: w.name ?? '',
        description: w.description,
        deliverable: w.deliverable,
        end_date: w.end_date ? dayjs(w.end_date) : null,
      }));
      const ms = res.drafts.milestones.map((m, i) => ({
        key: i,
        name: m.name ?? '',
        target_date: m.target_date ? dayjs(m.target_date) : null,
      }));
      const risks = res.drafts.risks.map((r, i) => ({
        key: i,
        title: r.title ?? '',
        probability: asGrade(r.probability),
        impact: asGrade(r.impact),
        mitigation: r.mitigation,
      }));
      setWbsRows(wbs);
      setMsRows(ms);
      setRiskRows(risks);
      setWbsKeys(wbs.map((r) => r.key));
      setMsKeys(ms.map((r) => r.key));
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
        },
        wbs: wbsRows
          .filter((r) => wbsKeys.includes(r.key))
          .map((r) => ({
            code: r.code,
            name: r.name,
            description: r.description,
            deliverable: r.deliverable,
            end_date: r.end_date ? r.end_date.format('YYYY-MM-DD') : null,
          })),
        milestones: msRows
          .filter((r) => msKeys.includes(r.key))
          .map((r) => ({
            name: r.name,
            target_date: r.target_date ? r.target_date.format('YYYY-MM-DD') : null,
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
      message.success(`章程导入成功，项目 ${res.project_code} 已创建`);
      onClose();
      navigate(`/projects/${res.project_id}`);
    } catch {
      // 已统一提示
    } finally {
      setCreating(false);
    }
  };

  const wbsColumns: ColumnsType<WbsRowState> = [
    { title: '编号', dataIndex: 'code', width: 64, render: (v) => v || '-' },
    {
      title: '任务名称',
      dataIndex: 'name',
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
    { title: '交付物', dataIndex: 'deliverable', width: 180, ellipsis: true, render: (v) => v || '-' },
    {
      title: '完成日期',
      dataIndex: 'end_date',
      width: 140,
      render: (_, r) => (
        <DatePicker
          size="small"
          value={r.end_date}
          onChange={(d) =>
            setWbsRows((rows) => rows.map((x) => (x.key === r.key ? { ...x, end_date: d } : x)))
          }
        />
      ),
    },
  ];

  const msColumns: ColumnsType<MsRowState> = [
    {
      title: '里程碑名称',
      dataIndex: 'name',
      render: (_, r) => (
        <Input
          size="small"
          value={r.name}
          maxLength={200}
          onChange={(e) =>
            setMsRows((rows) => rows.map((x) => (x.key === r.key ? { ...x, name: e.target.value } : x)))
          }
        />
      ),
    },
    {
      title: '目标日期',
      dataIndex: 'target_date',
      width: 140,
      render: (_, r) => (
        <DatePicker
          size="small"
          value={r.target_date}
          onChange={(d) =>
            setMsRows((rows) => rows.map((x) => (x.key === r.key ? { ...x, target_date: d } : x)))
          }
        />
      ),
    },
  ];

  const riskColumns: ColumnsType<RiskRowState> = [
    {
      title: '风险标题',
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
      title: '概率',
      dataIndex: 'probability',
      width: 90,
      render: (_, r) => (
        <Select
          size="small"
          value={r.probability}
          style={{ width: 72 }}
          options={RISK_GRADES.map((g) => ({ value: g, label: g }))}
          onChange={(v) =>
            setRiskRows((rows) => rows.map((x) => (x.key === r.key ? { ...x, probability: v } : x)))
          }
        />
      ),
    },
    {
      title: '影响',
      dataIndex: 'impact',
      width: 90,
      render: (_, r) => (
        <Select
          size="small"
          value={r.impact}
          style={{ width: 72 }}
          options={RISK_GRADES.map((g) => ({ value: g, label: g }))}
          onChange={(v) =>
            setRiskRows((rows) => rows.map((x) => (x.key === r.key ? { ...x, impact: v } : x)))
          }
        />
      ),
    },
    { title: '应对措施', dataIndex: 'mitigation', ellipsis: true, render: (v) => v || '-' },
  ];

  const memberOptions = members.map((m) => ({
    value: m.id,
    label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
  }));
  const pmLabel = (id?: string) => memberOptions.find((o) => o.value === id)?.label ?? id ?? '-';

  return (
    <Modal
      title="章程导入"
      open={open}
      width={960}
      onCancel={onClose}
      maskClosable={false}
      footer={
        step === 0 ? (
          <Space>
            <Button onClick={onClose}>取消</Button>
            <Button type="primary" disabled={!parsed} onClick={() => void goConfirm()}>
              下一步
            </Button>
          </Space>
        ) : (
          <Space>
            <Button onClick={() => setStep(0)}>上一步</Button>
            <Button type="primary" loading={creating} onClick={() => void submitCreate()}>
              确认创建
            </Button>
          </Space>
        )
      }
    >
      <Steps
        size="small"
        current={step}
        items={[{ title: '上传并解析' }, { title: '确认创建' }]}
        style={{ marginBottom: 16, maxWidth: 420 }}
      />

      {/* 第一步：上传 + 解析结果编辑（第二步时隐藏而非卸载，保留表单值） */}
      <div style={{ display: step === 0 ? 'block' : 'none' }}>
        {!parsed ? (
          <Spin spinning={parsing} tip="正在解析章程…">
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
              <p className="ant-upload-text">点击或拖拽《项目章程》.docx 到此处解析</p>
              <p className="ant-upload-hint">
                系统将自动提取项目字段，并生成 WBS / 里程碑 / 风险草稿，供确认后一键创建
              </p>
            </Upload.Dragger>
          </Spin>
        ) : (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Space>
              <FileWordOutlined style={{ color: '#1677ff' }} />
              <Typography.Text>{fileName}</Typography.Text>
              <Button size="small" onClick={() => setParsed(null)}>
                重新上传
              </Button>
            </Space>

            {parsed.warnings.length > 0 && (
              <Alert
                type="warning"
                showIcon
                message="解析提醒"
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
                  label="项目名称"
                  rules={[
                    { required: true, message: '请输入项目名称' },
                    { min: 2, message: '至少 2 个字符' },
                  ]}
                  style={{ width: 300, marginBottom: 8 }}
                >
                  <Input maxLength={200} />
                </Form.Item>
                <Form.Item
                  name="pm"
                  label="项目经理"
                  rules={[{ required: true, message: '请选择项目经理' }]}
                  style={{ width: 220, marginBottom: 8 }}
                >
                  <Select showSearch optionFilterProp="label" options={memberOptions} placeholder="选择人员" />
                </Form.Item>
                <Form.Item
                  name="planned"
                  label="计划起止"
                  rules={[{ required: true, message: '请选择计划起止日期' }]}
                  style={{ marginBottom: 8 }}
                >
                  <DatePicker.RangePicker />
                </Form.Item>
                <Form.Item name="budget_10k" label="预算（万元）" style={{ width: 150, marginBottom: 8 }}>
                  <InputNumber min={0} precision={2} style={{ width: '100%' }} />
                </Form.Item>
              </Space>
              <Form.Item name="description" label="项目描述" style={{ marginBottom: 8 }}>
                <Input.TextArea rows={3} maxLength={2000} />
              </Form.Item>
            </Form>

            <Typography.Text strong>WBS 任务草稿（勾选导入，可改名称与日期）</Typography.Text>
            <Table<WbsRowState>
              size="small"
              rowKey="key"
              columns={wbsColumns}
              dataSource={wbsRows}
              pagination={false}
              rowSelection={{ selectedRowKeys: wbsKeys, onChange: setWbsKeys }}
              locale={{ emptyText: '未解析到 WBS 草稿' }}
            />
            <Typography.Text strong>里程碑草稿</Typography.Text>
            <Table<MsRowState>
              size="small"
              rowKey="key"
              columns={msColumns}
              dataSource={msRows}
              pagination={false}
              rowSelection={{ selectedRowKeys: msKeys, onChange: setMsKeys }}
              locale={{ emptyText: '未解析到里程碑草稿' }}
            />
            <Typography.Text strong>风险草稿</Typography.Text>
            <Table<RiskRowState>
              size="small"
              rowKey="key"
              columns={riskColumns}
              dataSource={riskRows}
              pagination={false}
              rowSelection={{ selectedRowKeys: riskKeys, onChange: setRiskKeys }}
              locale={{ emptyText: '未解析到风险草稿' }}
            />
          </Space>
        )}
      </div>

      {/* 第二步：确认 */}
      {step === 1 && confirmed && (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="项目名称">{confirmed.name}</Descriptions.Item>
            <Descriptions.Item label="项目经理">{pmLabel(confirmed.pm)}</Descriptions.Item>
            <Descriptions.Item label="计划起止">
              {confirmed.planned[0].format('YYYY-MM-DD')} ~ {confirmed.planned[1].format('YYYY-MM-DD')}
            </Descriptions.Item>
            <Descriptions.Item label="预算（万元）">{confirmed.budget_10k ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="描述" span={2}>
              <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                {confirmed.description || '-'}
              </Typography.Paragraph>
            </Descriptions.Item>
          </Descriptions>
          <Alert
            type="info"
            showIcon
            message={`确认后将创建项目，并生成 ${wbsKeys.length} 个 WBS 任务、${msKeys.length} 个里程碑、${riskKeys.length} 条风险`}
            description="未指派负责人的任务默认由项目经理负责；缺少日期的任务将按项目计划顺延推算。"
          />
        </Space>
      )}
    </Modal>
  );
}
