import { useEffect, useState } from 'react';
import { DatePicker, Form, Input, InputNumber, Modal, Select, message } from 'antd';
import dayjs, { Dayjs } from 'dayjs';
import { api } from '../../api/client';
import { useT } from '../../i18n';
import type { Member, Portfolio, ServiceItem } from '../../api/types';

/** 共享编辑弹窗所需的项目字段（列表行缺 service_item_id/description，需先取详情再打开） */
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
    });
    // 下拉数据惰性加载（同原 ProjectDetail 编辑弹窗取数方式）
    if (members.length === 0) {
      api
        .getList<Member>('/members', { page: 1, page_size: 999 })
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
      });
      message.success(t('proj.projectUpdated'));
      onSaved();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={t('proj.editProjectTitle')}
      open={!!project}
      width={560}
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
      </Form>
    </Modal>
  );
}
