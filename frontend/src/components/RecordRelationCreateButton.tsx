import { useEffect, useRef, useState } from 'react';
import { Button, DatePicker, Drawer, Form, Input, Select, Space, message } from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { LinkOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { Member, ServiceItem } from '../api/types';
import { useT } from '../i18n';

type EntityType = 'ticket' | 'problem' | 'requirement';
type RelationType = 'upgraded_to_incident' | 'root_cause_of' | 'remediated_by_change' | 'converted_to_project';
type TargetEntityType = 'ticket' | 'problem' | 'project';
type TargetRecordType = 'incident' | 'change' | null;

interface PrepareResult {
  source: { code: string; title: string };
  relation_type: RelationType;
  target_entity_type: TargetEntityType;
  target_record_type: TargetRecordType;
  defaults: Record<string, unknown>;
  required_fields: string[];
}

interface SubmitResult {
  target: { entity_type: TargetEntityType; id: string; record_type?: string; code: string };
  relation: { id: string; relation_type: RelationType };
  idempotent_replay: boolean;
}

function targetPath(target: SubmitResult['target']) {
  if (target.entity_type === 'ticket') {
    const section = target.record_type === 'incident' ? 'incidents' : target.record_type === 'change' ? 'changes' : 'tickets';
    return `/itsm/${section}/${target.id}`;
  }
  if (target.entity_type === 'problem') return `/itsm/problems/${target.id}`;
  return `/projects/${target.id}`;
}

function newIdempotencyKey() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return `relation-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

/**
 * 统一“创建目标并关联”入口。后端以来源记录、目标类型和幂等键复核全部权限，
 * 本组件只负责展示服务器返回的安全默认值和收集目标领域所需字段。
 */
export default function RecordRelationCreateButton({
  sourceEntityType,
  sourceId,
  relationType,
  disabled = false,
  onCreated,
}: {
  sourceEntityType: EntityType;
  sourceId: string;
  relationType: RelationType;
  disabled?: boolean;
  onCreated?: () => void;
}) {
  const t = useT();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [prepared, setPrepared] = useState<PrepareResult | null>(null);
  const [items, setItems] = useState<ServiceItem[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [form] = Form.useForm();
  const idempotencyKey = useRef('');

  const openDrawer = () => {
    idempotencyKey.current = newIdempotencyKey();
    form.resetFields();
    setPrepared(null);
    setOpen(true);
  };

  useEffect(() => {
    if (!open) return;
    let active = true;
    setPreparing(true);
    api
      .post<PrepareResult>('/record-relations/prepare', {
        source_entity_type: sourceEntityType,
        source_entity_id: sourceId,
        relation_type: relationType,
      })
      .then((data) => {
        if (!active) return;
        setPrepared(data);
        const defaults = { ...data.defaults } as Record<string, unknown>;
        if (defaults.planned_start && defaults.planned_end) {
          defaults.planned_range = [dayjs(String(defaults.planned_start)), dayjs(String(defaults.planned_end))];
        }
        form.setFieldsValue(defaults);
      })
      .catch(() => setOpen(false))
      .finally(() => active && setPreparing(false));
    if (items.length === 0) {
      api.getList<ServiceItem>('/service-items').then((res) => setItems(res.items.filter((item) => item.status === '上架'))).catch(() => undefined);
    }
    if (members.length === 0) {
      api.getList<Member>('/members', { page: 1, page_size: 2000, scope: 'it' }).then((res) => setMembers(res.items)).catch(() => undefined);
    }
    return () => {
      active = false;
    };
  }, [form, items.length, members.length, open, relationType, sourceEntityType, sourceId]);

  const submit = async () => {
    if (!prepared) return;
    const values = await form.validateFields();
    const target: Record<string, unknown> = {
      ...values,
      planned_range: undefined,
    };
    const planned = values.planned_range as [Dayjs, Dayjs] | undefined;
    if (planned) {
      target.planned_start = planned[0].format('YYYY-MM-DD');
      target.planned_end = planned[1].format('YYYY-MM-DD');
    }
    Object.keys(target).forEach((key) => target[key] === undefined && delete target[key]);
    setSaving(true);
    try {
      const result = await api.post<SubmitResult>('/record-relations/submit', {
        source_entity_type: sourceEntityType,
        source_entity_id: sourceId,
        relation_type: relationType,
        reason: values.reason,
        idempotency_key: idempotencyKey.current,
        target,
      });
      message.success(result.idempotent_replay ? t('comp.relationCreate.replayed') : t('comp.relationCreate.success', { code: result.target.code }));
      setOpen(false);
      onCreated?.();
      navigate(targetPath(result.target));
    } catch {
      // 已由统一 API 客户端提示具体权限、字段或幂等错误。
    } finally {
      setSaving(false);
    }
  };

  const kind = prepared?.target_entity_type;
  const ticketKind = prepared?.target_record_type;
  const actionLabel = t(`comp.relationCreate.action.${relationType}`);

  return (
    <>
      <Button icon={<LinkOutlined />} onClick={openDrawer} disabled={disabled}>
        {actionLabel}
      </Button>
      <Drawer
        title={t('comp.relationCreate.title', { action: actionLabel })}
        open={open}
        width={560}
        destroyOnClose
        onClose={() => setOpen(false)}
        extra={(
          <Space>
            <Button onClick={() => setOpen(false)}>{t('common.cancel')}</Button>
            <Button type="primary" loading={saving} disabled={preparing || !prepared} onClick={() => void submit()}>
              {t('comp.relationCreate.submit')}
            </Button>
          </Space>
        )}
      >
        <Form form={form} layout="vertical" requiredMark="optional">
          {prepared && (
            <Form.Item>
              <span className="ant-form-text">{t('comp.relationCreate.source', { code: prepared.source.code, title: prepared.source.title })}</span>
            </Form.Item>
          )}

          {(kind === 'ticket' || kind === 'problem') && (
            <>
              <Form.Item name="title" label={t('comp.relationCreate.field.title')} rules={[{ required: true, min: 2, max: 200 }]}>
                <Input maxLength={200} />
              </Form.Item>
              <Form.Item name="description" label={t('comp.relationCreate.field.description')} rules={[{ required: true, min: 1 }]}>
                <Input.TextArea autoSize={{ minRows: 4, maxRows: 8 }} />
              </Form.Item>
              <Space style={{ width: '100%' }} align="start">
                <Form.Item name="priority" label={t('comp.relationCreate.field.priority')} rules={[{ required: true }]} style={{ minWidth: 160 }}>
                  <Select options={['P1', 'P2', 'P3', 'P4'].map((value) => ({ value, label: value }))} />
                </Form.Item>
                {kind === 'problem' && (
                  <Form.Item name="assigned_line" label={t('comp.relationCreate.field.line')} rules={[{ required: true }]} style={{ minWidth: 180 }}>
                    <Select options={[
                      { value: 'product', label: t('comp.relationCreate.line.product') },
                      { value: 'ops', label: t('comp.relationCreate.line.ops') },
                      { value: 'dev', label: t('comp.relationCreate.line.dev') },
                    ]} />
                  </Form.Item>
                )}
              </Space>
              <Form.Item name="service_item_id" label={t('comp.relationCreate.field.serviceItem')} rules={[{ required: kind === 'ticket' }]}>
                <Select
                  allowClear={kind === 'problem'}
                  showSearch
                  optionFilterProp="label"
                  options={items.map((item) => ({ value: item.id, label: `${item.item_code} · ${item.name}` }))}
                />
              </Form.Item>
            </>
          )}

          {kind === 'ticket' && ticketKind === 'change' && (
            <>
              <Space style={{ width: '100%' }} align="start">
                <Form.Item name="change_type" label={t('comp.relationCreate.field.changeType')} rules={[{ required: true }]} style={{ minWidth: 180 }}>
                  <Select options={['标准', '普通', '紧急'].map((value) => ({ value, label: value }))} />
                </Form.Item>
                <Form.Item name="risk_level" label={t('comp.relationCreate.field.risk')} style={{ minWidth: 160 }}>
                  <Select allowClear options={['高', '中', '低'].map((value) => ({ value, label: value }))} />
                </Form.Item>
              </Space>
              <Form.Item name="change_reason" label={t('comp.relationCreate.field.changeReason')}>
                <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} />
              </Form.Item>
              <Form.Item name="implementation_plan" label={t('comp.relationCreate.field.implementationPlan')}>
                <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} />
              </Form.Item>
              <Form.Item name="rollback_plan" label={t('comp.relationCreate.field.rollbackPlan')}>
                <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} />
              </Form.Item>
            </>
          )}

          {kind === 'project' && (
            <>
              <Form.Item name="name" label={t('comp.relationCreate.field.projectName')} rules={[{ required: true, min: 2, max: 200 }]}>
                <Input maxLength={200} />
              </Form.Item>
              <Form.Item name="pm" label={t('comp.relationCreate.field.pm')} rules={[{ required: true }]}>
                <Select showSearch optionFilterProp="label" options={members.map((member) => ({ value: member.id, label: member.department_name ? `${member.name}（${member.department_name}）` : member.name }))} />
              </Form.Item>
              <Form.Item name="planned_range" label={t('comp.relationCreate.field.plannedRange')} rules={[{ required: true }]}>
                <DatePicker.RangePicker style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="description" label={t('comp.relationCreate.field.description')}>
                <Input.TextArea autoSize={{ minRows: 4, maxRows: 8 }} />
              </Form.Item>
            </>
          )}

          <Form.Item name="reason" label={t('comp.relationCreate.field.reason')} extra={t('comp.relationCreate.reasonHint')} rules={[{ required: true, min: 5, max: 1000 }]}>
            <Input.TextArea autoSize={{ minRows: 3, maxRows: 6 }} maxLength={1000} />
          </Form.Item>
        </Form>
      </Drawer>
    </>
  );
}
