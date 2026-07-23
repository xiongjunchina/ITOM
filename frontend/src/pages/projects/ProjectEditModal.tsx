import { useEffect, useState } from 'react';
import { Button, Collapse, DatePicker, Form, Input, InputNumber, Modal, Select, Space, message } from 'antd';
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { api } from '../../api/client';
import { useT } from '../../i18n';
import type { Member, Portfolio, ProjectOrgEntry, ServiceItem } from '../../api/types';

/** 共享编辑弹窗所需的项目字段（列表行缺 service_item_id/description/章程字段，需先取详情再打开） */
export interface ProjectEditModalProject {
  id: string;
  name: string;
  pm: string;
  planned_start: string;
  planned_end: string;
  portfolio_id: string | null;
  service_item_id: string | null;
  budget_10k: number | null;
  description: string | null;
  actual_start: string | null;
  actual_end: string | null;
  // ---- M13 章程信息 ----
  background: string | null;
  goals: string | null;
  scope_in: string | null;
  scope_out: string | null;
  resource_note: string | null;
  org_members: ProjectOrgEntry[];
  stakeholders: ProjectOrgEntry[];
}

/** Form.List 行值（Input 产出 string；初值可能带 undefined） */
interface OrgEntryFormValue {
  name: string;
  role?: string;
  duty?: string;
}

interface ProjectEditFormValues {
  name: string;
  pm: string;
  planned: [Dayjs, Dayjs];
  portfolio_id?: string;
  service_item_id?: string;
  budget_10k?: number;
  description?: string;
  actual_start?: Dayjs | null;
  actual_end?: Dayjs | null;
  background?: string;
  goals?: string;
  scope_in?: string;
  scope_out?: string;
  resource_note?: string;
  org_members?: OrgEntryFormValue[];
  stakeholders?: OrgEntryFormValue[];
}

/** 组织条目 Form.List 行 → PATCH 载荷（空串归 null；空数组照发实现清空语义） */
function toOrgPayload(rows: OrgEntryFormValue[] | undefined): ProjectOrgEntry[] {
  return (rows ?? []).map((r) => ({ name: r.name, role: r.role || null, duty: r.duty || null }));
}

/**
 * 项目基本信息编辑弹窗（项目列表行内编辑 / 项目详情共用）：
 * project 非空即打开；内部自取 members/portfolios/service-items 下拉数据；
 * 提交 PATCH /projects/{id}（含实际起止，清空提交 null）后 message + onSaved。
 */
export default function ProjectEditModal({
  project,
  onClose,
  onSaved,
}: {
  project: ProjectEditModalProject | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useT();
  const [form] = Form.useForm<ProjectEditFormValues>();
  const [saving, setSaving] = useState(false);
  const [members, setMembers] = useState<Member[]>([]);
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [serviceItems, setServiceItems] = useState<ServiceItem[]>([]);

  useEffect(() => {
    if (!project) return;
    form.setFieldsValue({
      name: project.name,
      pm: project.pm,
      planned: [dayjs(project.planned_start), dayjs(project.planned_end)],
      portfolio_id: project.portfolio_id ?? undefined,
      service_item_id: project.service_item_id ?? undefined,
      budget_10k: project.budget_10k ?? undefined,
      description: project.description ?? undefined,
      actual_start: project.actual_start ? dayjs(project.actual_start) : null,
      actual_end: project.actual_end ? dayjs(project.actual_end) : null,
      background: project.background ?? undefined,
      goals: project.goals ?? undefined,
      scope_in: project.scope_in ?? undefined,
      scope_out: project.scope_out ?? undefined,
      resource_note: project.resource_note ?? undefined,
      org_members: (project.org_members ?? []).map((m) => ({
        name: m.name,
        role: m.role ?? undefined,
        duty: m.duty ?? undefined,
      })),
      stakeholders: (project.stakeholders ?? []).map((m) => ({
        name: m.name,
        role: m.role ?? undefined,
        duty: m.duty ?? undefined,
      })),
    });
    // 下拉数据惰性加载（同原 ProjectDetail 编辑弹窗取数方式）
    if (members.length === 0) {
      api
        .getList<Member>('/members', { page: 1, page_size: 2000, scope: 'it' })
        .then((res) => setMembers(res.items))
        .catch(() => undefined);
    }
    if (portfolios.length === 0) {
      api
        .getList<Portfolio>('/portfolios')
        .then((res) => setPortfolios(res.items))
        .catch(() => undefined);
    }
    if (serviceItems.length === 0) {
      api
        .getList<ServiceItem>('/service-items')
        .then((res) => setServiceItems(res.items))
        .catch(() => undefined);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project]);

  const submit = async () => {
    if (!project) return;
    const v = await form.validateFields();
    setSaving(true);
    try {
      await api.patch(`/projects/${project.id}`, {
        name: v.name,
        pm: v.pm,
        planned_start: v.planned[0].format('YYYY-MM-DD'),
        planned_end: v.planned[1].format('YYYY-MM-DD'),
        portfolio_id: v.portfolio_id ?? null,
        service_item_id: v.service_item_id ?? null,
        budget_10k: v.budget_10k ?? null,
        description: v.description || null,
        actual_start: v.actual_start ? v.actual_start.format('YYYY-MM-DD') : null,
        actual_end: v.actual_end ? v.actual_end.format('YYYY-MM-DD') : null,
        background: v.background || null,
        goals: v.goals || null,
        scope_in: v.scope_in || null,
        scope_out: v.scope_out || null,
        resource_note: v.resource_note || null,
        org_members: toOrgPayload(v.org_members),
        stakeholders: toOrgPayload(v.stakeholders),
      });
      message.success(t('proj.projectUpdated'));
      onSaved();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  /** 组织条目 Form.List（主要成员/关键干系人共用）：每行 姓名(必填)/角色/职责或关注点 + 删除，底部 dashed 添加按钮 */
  const orgFormList = (listName: 'org_members' | 'stakeholders') => {
    const isMember = listName === 'org_members';
    return (
      <Form.List name={listName}>
        {(fields, { add, remove }) => (
          <>
            {fields.map(({ key, name, ...restField }) => (
              <Space key={key} align="baseline" style={{ display: 'flex', marginBottom: 8 }}>
                <Form.Item
                  {...restField}
                  name={[name, 'name']}
                  rules={[{ required: true, message: t('proj.charter.nameRequired') }]}
                  style={{ marginBottom: 0 }}
                >
                  <Input placeholder={t('proj.charter.col.name')} maxLength={50} style={{ width: 130 }} />
                </Form.Item>
                <Form.Item {...restField} name={[name, 'role']} style={{ marginBottom: 0 }}>
                  <Input
                    placeholder={t(isMember ? 'proj.charter.col.role' : 'proj.charter.col.sRole')}
                    maxLength={100}
                    style={{ width: 170 }}
                  />
                </Form.Item>
                <Form.Item {...restField} name={[name, 'duty']} style={{ marginBottom: 0 }}>
                  <Input
                    placeholder={t(isMember ? 'proj.charter.col.duty' : 'proj.charter.col.concern')}
                    maxLength={200}
                    style={{ width: 240 }}
                  />
                </Form.Item>
                <Button type="text" danger icon={<MinusCircleOutlined />} onClick={() => remove(name)} />
              </Space>
            ))}
            <Button type="dashed" block icon={<PlusOutlined />} onClick={() => add()}>
              {t(isMember ? 'proj.charter.addMember' : 'proj.charter.addStakeholder')}
            </Button>
          </>
        )}
      </Form.List>
    );
  };

  return (
    <Modal
      title={t('proj.editProjectTitle')}
      open={!!project}
      width={720}
      onOk={() => void submit()}
      confirmLoading={saving}
      onCancel={onClose}
      destroyOnClose
    >
      <Form<ProjectEditFormValues> form={form} layout="vertical">
        <Form.Item
          name="name"
          label={t('proj.projectName')}
          rules={[
            { required: true, message: t('proj.projectNameRequired') },
            { min: 2, message: t('proj.min2') },
          ]}
        >
          <Input maxLength={200} />
        </Form.Item>
        <Form.Item name="pm" label={t('proj.pm')} rules={[{ required: true, message: t('proj.pmRequired') }]}>
          <Select
            showSearch
            optionFilterProp="label"
            options={members.map((m) => ({
              value: m.id,
              label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
            }))}
          />
        </Form.Item>
        <Form.Item name="planned" label={t('proj.planned')} rules={[{ required: true, message: t('proj.plannedRequired') }]}>
          <DatePicker.RangePicker style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="actual_start" label={t('proj.actualStart')}>
          <DatePicker style={{ width: '100%' }} allowClear />
        </Form.Item>
        <Form.Item
          name="actual_end"
          label={t('proj.actualEnd')}
          dependencies={['actual_start']}
          rules={[
            ({ getFieldValue }) => ({
              validator(_, value: Dayjs | null | undefined) {
                const start = getFieldValue('actual_start') as Dayjs | null | undefined;
                if (value && start && value.isBefore(start, 'day')) {
                  return Promise.reject(new Error(t('proj.actualEndBeforeStart')));
                }
                return Promise.resolve();
              },
            }),
          ]}
        >
          <DatePicker style={{ width: '100%' }} allowClear />
        </Form.Item>
        <Form.Item name="portfolio_id" label={t('proj.belongPortfolio')}>
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            options={portfolios.map((p) => ({ value: p.id, label: p.name }))}
          />
        </Form.Item>
        <Form.Item name="service_item_id" label={t('proj.linkedService')}>
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            options={serviceItems.map((i) => ({
              value: i.id,
              label: `${i.name}（${i.catalog_name ?? i.item_code}）`,
            }))}
          />
        </Form.Item>
        <Form.Item name="budget_10k" label={t('proj.budgetWan')}>
          <InputNumber min={0} precision={2} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="description" label={t('proj.desc')}>
          <Input.TextArea rows={3} maxLength={2000} />
        </Form.Item>

        {/* M13 章程信息（默认收起；forceRender 保证未展开时字段仍注册提交，避免误清空） */}
        <Collapse
          size="small"
          items={[
            {
              key: 'charter',
              label: t('proj.charter.editSection'),
              forceRender: true,
              children: (
                <>
                  <Form.Item name="background" label={t('proj.charter.background')}>
                    <Input.TextArea rows={3} maxLength={2000} />
                  </Form.Item>
                  <Form.Item name="goals" label={t('proj.charter.goals')}>
                    <Input.TextArea rows={3} maxLength={2000} />
                  </Form.Item>
                  <Form.Item name="scope_in" label={t('proj.charter.scopeIn')}>
                    <Input.TextArea rows={2} maxLength={2000} />
                  </Form.Item>
                  <Form.Item name="scope_out" label={t('proj.charter.scopeOut')}>
                    <Input.TextArea rows={2} maxLength={2000} />
                  </Form.Item>
                  <Form.Item name="resource_note" label={t('proj.charter.resourceNote')}>
                    <Input.TextArea rows={2} maxLength={2000} />
                  </Form.Item>
                  <Form.Item label={t('proj.charter.members')} style={{ marginBottom: 12 }}>
                    {orgFormList('org_members')}
                  </Form.Item>
                  <Form.Item label={t('proj.charter.stakeholders')} style={{ marginBottom: 0 }}>
                    {orgFormList('stakeholders')}
                  </Form.Item>
                </>
              ),
            },
          ]}
        />
      </Form>
    </Modal>
  );
}
