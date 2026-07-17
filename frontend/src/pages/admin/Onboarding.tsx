import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { api } from '../../api/client';
import type { Lang } from '../../i18n/store';
import { useT } from '../../i18n';
import type { Member, OnboardingRequest, OnboardingStatus, RoleDef } from '../../api/types';

interface ApproveForm {
  username: string;
  roles?: string[];
  language: Lang;
  person_id?: string | null;
  note?: string;
}

const STATUS_TAG: Record<OnboardingStatus, string> = {
  pending: 'orange',
  approved: 'green',
  rejected: 'red',
};

/** 管理员登录开通审批：按状态筛选申请，开通(赋用户名/角色/语言/关联人员) 或 驳回 */
export default function Onboarding({ onChanged }: { onChanged?: () => void }) {
  const t = useT();
  const [status, setStatus] = useState<OnboardingStatus>('pending');
  const [rows, setRows] = useState<OnboardingRequest[]>([]);
  const [loading, setLoading] = useState(false);

  const [roles, setRoles] = useState<RoleDef[]>([]);
  const [members, setMembers] = useState<Member[]>([]);

  const [approveTarget, setApproveTarget] = useState<OnboardingRequest | null>(null);
  const [approveForm] = Form.useForm<ApproveForm>();
  const [approving, setApproving] = useState(false);

  const [rejectTarget, setRejectTarget] = useState<OnboardingRequest | null>(null);
  const [rejectForm] = Form.useForm<{ reason: string }>();
  const [rejecting, setRejecting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<OnboardingRequest>('/auth/onboarding/requests', { status });
      setRows(res.items);
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    api
      .getList<RoleDef>('/admin/roles')
      .then((res) => setRoles(res.items.filter((r) => r.code !== 'admin')))
      .catch(() => undefined);
    api
      .getList<Member>('/members', { page_size: 2000 })
      .then((res) => setMembers(res.items))
      .catch(() => undefined);
  }, []);

  const openApprove = (record: OnboardingRequest) => {
    setApproveTarget(record);
    approveForm.resetFields();
    // 组织同步自动匹配到的人员（open_id/手机/邮箱）→ 预填关联人员
    approveForm.setFieldsValue({ language: 'zh', person_id: record.matched_person_id ?? undefined });
  };

  const submitApprove = async () => {
    if (!approveTarget) return;
    const values = await approveForm.validateFields();
    setApproving(true);
    try {
      await api.post(`/auth/onboarding/requests/${approveTarget.id}/approve`, {
        username: values.username.trim(),
        roles: values.roles ?? [],
        language: values.language,
        person_id: values.person_id ?? undefined,
        note: values.note?.trim() || undefined,
      });
      message.success(t('onboarding.approved.done'));
      setApproveTarget(null);
      void load();
      onChanged?.();
    } catch {
      // 已统一提示（USERNAME_TAKEN / INVALID_ROLE / ADMIN_NOT_GRANTABLE / ALREADY_PROCESSED）
    } finally {
      setApproving(false);
    }
  };

  const submitReject = async () => {
    if (!rejectTarget) return;
    const { reason } = await rejectForm.validateFields();
    setRejecting(true);
    try {
      await api.post(`/auth/onboarding/requests/${rejectTarget.id}/reject`, { reason: reason.trim() });
      message.success(t('onboarding.rejected.done'));
      setRejectTarget(null);
      void load();
      onChanged?.();
    } catch {
      // 已统一提示
    } finally {
      setRejecting(false);
    }
  };

  const statusLabel = (s: OnboardingStatus) =>
    t(s === 'pending' ? 'onboarding.pending' : s === 'approved' ? 'onboarding.approvedTab' : 'onboarding.rejectedTab');

  const columns: ColumnsType<OnboardingRequest> = [
    { title: t('onboarding.applicant'), dataIndex: 'display_name', width: 160 },
    {
      title: t('onboarding.source'),
      dataIndex: 'external_source',
      width: 100,
      render: (v: string) => (v === 'feishu' ? t('onboarding.sourceFeishu') : v || '-'),
    },
    {
      title: t('onboarding.contact'),
      key: 'contact',
      width: 200,
      render: (_, r) => r.email || r.mobile || '-',
    },
    {
      title: t('onboarding.requestedAt'),
      dataIndex: 'requested_at',
      width: 170,
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'),
    },
    {
      title: t('common.status'),
      dataIndex: 'status',
      width: 160,
      render: (s: OnboardingStatus, r) => (
        <Space size={4}>
          <Tag color={STATUS_TAG[s]}>{statusLabel(s)}</Tag>
          {s === 'rejected' && r.note ? (
            <Typography.Text type="secondary" ellipsis={{ tooltip: r.note }} style={{ maxWidth: 90 }}>
              {r.note}
            </Typography.Text>
          ) : null}
        </Space>
      ),
    },
    {
      title: t('common.actions'),
      key: 'action',
      width: 140,
      render: (_, r) =>
        r.status === 'pending' ? (
          <Space>
            <Button type="link" size="small" onClick={() => openApprove(r)}>
              {t('onboarding.approve')}
            </Button>
            <Button
              type="link"
              size="small"
              danger
              onClick={() => {
                rejectForm.resetFields();
                setRejectTarget(r);
              }}
            >
              {t('onboarding.reject')}
            </Button>
          </Space>
        ) : (
          '-'
        ),
    },
  ];

  const roleOptions = useMemo(() => roles.map((r) => ({ value: r.code, label: r.name })), [roles]);
  const memberOptions = useMemo(() => {
    const opts = members.map((m) => ({
      value: m.id,
      label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
    }));
    // 兜底：自动匹配到的人员若不在已加载列表（超出分页上限），并入选项保证预填可见
    if (
      approveTarget?.matched_person_id &&
      !members.some((m) => m.id === approveTarget.matched_person_id)
    ) {
      opts.unshift({
        value: approveTarget.matched_person_id,
        label: approveTarget.matched_person_name ?? approveTarget.matched_person_id,
      });
    }
    return opts;
  }, [members, approveTarget]);

  return (
    <Card
      title={t('onboarding.tab')}
      extra={
        <Segmented
          value={status}
          onChange={(v) => setStatus(v as OnboardingStatus)}
          options={[
            { value: 'pending', label: t('onboarding.pending') },
            { value: 'approved', label: t('onboarding.approvedTab') },
            { value: 'rejected', label: t('onboarding.rejectedTab') },
          ]}
        />
      }
    >
      <Table<OnboardingRequest>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={false}
        locale={{
          emptyText:
            status === 'pending' ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('onboarding.emptyPending')} />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('common.noData')} />
            ),
        }}
      />

      <Modal
        title={t('onboarding.approveTitle')}
        open={!!approveTarget}
        onOk={() => void submitApprove()}
        okText={t('common.confirm')}
        cancelText={t('common.cancel')}
        confirmLoading={approving}
        onCancel={() => setApproveTarget(null)}
        destroyOnClose
      >
        <Typography.Paragraph type="secondary">
          {t('onboarding.hello', { name: approveTarget?.display_name || '' })}
        </Typography.Paragraph>
        <Form<ApproveForm> form={approveForm} layout="vertical" preserve={false}>
          <Form.Item
            name="username"
            label={t('onboarding.setUsername')}
            extra={t('onboarding.setUsernameHint')}
            rules={[
              { required: true, message: t('onboarding.usernameRequired') },
              { pattern: /^[A-Za-z0-9_.\-]+$/, message: t('onboarding.usernamePattern') },
            ]}
          >
            <Input maxLength={50} autoComplete="off" />
          </Form.Item>
          <Form.Item name="roles" label={t('onboarding.setRoles')}>
            <Select mode="multiple" allowClear options={roleOptions} placeholder={t('onboarding.setRoles')} />
          </Form.Item>
          <Form.Item name="language" label={t('onboarding.setLanguage')} initialValue="zh">
            <Select
              options={[
                { value: 'zh', label: t('lang.zh') },
                { value: 'en', label: t('lang.en') },
              ]}
            />
          </Form.Item>
          <Form.Item name="person_id" label={t('onboarding.linkPerson')} extra={t('onboarding.linkPersonHint')}>
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder={t('onboarding.linkPerson')}
              options={memberOptions}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={t('onboarding.rejectTitle')}
        open={!!rejectTarget}
        onOk={() => void submitReject()}
        okText={t('common.confirm')}
        cancelText={t('common.cancel')}
        confirmLoading={rejecting}
        onCancel={() => setRejectTarget(null)}
        destroyOnClose
      >
        <Form form={rejectForm} layout="vertical" preserve={false}>
          <Form.Item
            name="reason"
            label={t('onboarding.rejectReason')}
            rules={[{ required: true, message: t('onboarding.rejectReasonRequired') }]}
          >
            <Input.TextArea rows={3} maxLength={200} showCount />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
