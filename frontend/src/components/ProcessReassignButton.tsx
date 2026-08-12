import { useState } from 'react';
import { Button, Input, Modal, Select, Space, Typography, message } from 'antd';
import { SwapOutlined } from '@ant-design/icons';
import { api } from '../api/client';
import { useT } from '../i18n';
import { canHandleTask, useAuthStore } from '../stores/auth';
import type { FlowDiagramStep } from './FlowDiagram';

interface ReassignCandidate {
  id: string;
  name: string;
  department_name?: string | null;
}

/** 当前待办的通用转派入口：只变更处理人，不改变流程节点。 */
export default function ProcessReassignButton({
  step,
  disabled = false,
  onDone,
}: {
  step: FlowDiagramStep | null | undefined;
  disabled?: boolean;
  onDone: () => void;
}) {
  const t = useT();
  const user = useAuthStore((state) => state.user);
  const [open, setOpen] = useState(false);
  const [loadingMembers, setLoadingMembers] = useState(false);
  const [saving, setSaving] = useState(false);
  const [members, setMembers] = useState<ReassignCandidate[]>([]);
  const [assignee, setAssignee] = useState<string>();
  const [reason, setReason] = useState('');

  if (
    disabled ||
    !step?.task_id ||
    step.task_status !== '待处理' ||
    !canHandleTask(user, step)
  ) {
    return null;
  }

  const show = async () => {
    setOpen(true);
    setAssignee(undefined);
    setReason('');
    if (members.length > 0) return;
    setLoadingMembers(true);
    try {
      const result = await api.get<ReassignCandidate[]>(
        `/process-tasks/${step.task_id}/reassign-candidates`,
      );
      setMembers(result);
    } catch {
      setOpen(false);
    } finally {
      setLoadingMembers(false);
    }
  };

  const submit = async () => {
    if (!assignee) {
      message.warning(t('comp.flow.reassignAssigneeRequired'));
      return;
    }
    setSaving(true);
    try {
      await api.post(`/process-tasks/${step.task_id}/reassign`, {
        assignee,
        reason: reason.trim() || null,
      });
      message.success(t('comp.flow.reassigned'));
      setOpen(false);
      onDone();
    } catch {
      // 统一错误拦截器已提示
    } finally {
      setSaving(false);
    }
  };

  const options = members
    .filter((member) => member.id !== step.assignee)
    .map((member) => ({
      value: member.id,
      label: member.department_name ? `${member.name}（${member.department_name}）` : member.name,
    }));

  return (
    <>
      <Button icon={<SwapOutlined />} onClick={() => void show()}>
        {t('comp.flow.reassign')}
      </Button>
      <Modal
        title={t('comp.flow.reassignTitle')}
        open={open}
        confirmLoading={saving}
        okButtonProps={{ disabled: !assignee }}
        onOk={() => void submit()}
        onCancel={() => setOpen(false)}
        destroyOnClose
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <div>
            <Typography.Text strong>{t('comp.flow.reassignAssignee')}</Typography.Text>
            <Select
              showSearch
              optionFilterProp="label"
              loading={loadingMembers}
              value={assignee}
              onChange={setAssignee}
              options={options}
              placeholder={t('comp.flow.reassignPlaceholder')}
              style={{ width: '100%', marginTop: 6 }}
            />
          </div>
          <div>
            <Typography.Text strong>{t('comp.flow.reassignReason')}</Typography.Text>
            <Input.TextArea
              rows={3}
              maxLength={500}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder={t('comp.flow.reassignReasonPlaceholder')}
              style={{ marginTop: 6 }}
            />
          </div>
        </Space>
      </Modal>
    </>
  );
}
