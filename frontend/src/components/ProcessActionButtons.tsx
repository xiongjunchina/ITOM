import { useState } from 'react';
import { Button, Input, Modal, Space, message } from 'antd';
import { CheckOutlined, CloseOutlined } from '@ant-design/icons';
import { api } from '../api/client';
import { canHandleTask, useAuthStore } from '../stores/auth';
import { useT } from '../i18n';
import type { FlowDiagramStep } from './FlowDiagram';

/**
 * 审批节点右上角动作：同意理由可选，驳回理由必填。
 * 处理节点不显示这些按钮，统一使用流程图中的「完成此步骤」。
 */
export default function ProcessActionButtons({
  step,
  disabled = false,
  onDone,
}: {
  step: FlowDiagramStep | null | undefined;
  disabled?: boolean;
  onDone: () => void;
}) {
  const t = useT();
  const user = useAuthStore((s) => s.user);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [approvalOpen, setApprovalOpen] = useState(false);
  const [approvalComment, setApprovalComment] = useState('');
  const [saving, setSaving] = useState(false);

  if (
    disabled ||
    !step?.task_id ||
    step.task_status !== '待处理' ||
    step.node_type !== 'approval' ||
    !canHandleTask(user, step)
  ) {
    return null;
  }

  const approve = async () => {
    setSaving(true);
    try {
      await api.post(`/process-tasks/${step.task_id}/approve`, { comment: approvalComment.trim() });
      message.success(t('comp.flow.approved'));
      setApprovalOpen(false);
      setApprovalComment('');
      onDone();
    } catch {
      // 统一错误拦截器已提示
    } finally {
      setSaving(false);
    }
  };

  const reject = async () => {
    if (rejectReason.trim().length < 5) {
      message.warning(t('comp.flow.rejectReasonRequired'));
      return;
    }
    setSaving(true);
    try {
      await api.post(`/process-tasks/${step.task_id}/reject`, { reason: rejectReason.trim() });
      message.success(t('comp.flow.rejected'));
      setRejectOpen(false);
      setRejectReason('');
      onDone();
    } catch {
      // 统一错误拦截器已提示
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <Space wrap>
        <Button type="primary" icon={<CheckOutlined />} onClick={() => setApprovalOpen(true)}>
          {t('comp.flow.approve')}
        </Button>
        <Button danger icon={<CloseOutlined />} onClick={() => setRejectOpen(true)}>
          {t('comp.flow.reject')}
        </Button>
      </Space>
      <Modal
        title={t('comp.flow.approveTitle')}
        open={approvalOpen}
        confirmLoading={saving}
        onOk={() => void approve()}
        onCancel={() => setApprovalOpen(false)}
        destroyOnClose
      >
        <Input.TextArea
          rows={3}
          maxLength={500}
          value={approvalComment}
          onChange={(e) => setApprovalComment(e.target.value)}
          placeholder={t('comp.flow.approveCommentOptional')}
        />
      </Modal>
      <Modal
        title={t('comp.flow.rejectTitle')}
        open={rejectOpen}
        confirmLoading={saving}
        okButtonProps={{ danger: true }}
        onOk={() => void reject()}
        onCancel={() => setRejectOpen(false)}
        destroyOnClose
      >
        <Input.TextArea
          rows={4}
          maxLength={500}
          value={rejectReason}
          onChange={(e) => setRejectReason(e.target.value)}
          placeholder={t('comp.flow.rejectReasonPlaceholder')}
        />
      </Modal>
    </>
  );
}
