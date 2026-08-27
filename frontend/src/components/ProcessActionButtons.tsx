import { useState } from 'react';
import { Button, Input, Modal, Select, Space, Typography, message } from 'antd';
import { CheckOutlined, CloseOutlined } from '@ant-design/icons';
import { api } from '../api/client';
import { canHandleTask, useAuthStore } from '../stores/auth';
import { useT } from '../i18n';
import type { FlowDiagramStep } from './FlowDiagram';
import ProcessReassignButton from './ProcessReassignButton';

/**
 * 当前流程节点动作：所有节点均可转派；审批节点额外显示同意与驳回。
 */
export default function ProcessActionButtons({
  step,
  returnTargets = [],
  disabled = false,
  onDone,
}: {
  step: FlowDiagramStep | null | undefined;
  returnTargets?: { seq: number; name: string; kind: 'process_step' | 'requester_supplement' }[];
  disabled?: boolean;
  onDone: () => void;
}) {
  const t = useT();
  const user = useAuthStore((s) => s.user);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [returnTarget, setReturnTarget] = useState<number | undefined>();
  const [approvalOpen, setApprovalOpen] = useState(false);
  const [approvalComment, setApprovalComment] = useState('');
  const [saving, setSaving] = useState(false);

  if (
    disabled ||
    !step?.task_id ||
    step.task_status !== '待处理' ||
    !canHandleTask(user, step)
  ) {
    return null;
  }

  const isApproval = step.node_type === 'approval';

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
      await api.post(`/process-tasks/${step.task_id}/reject`, {
        reason: rejectReason.trim(),
        ...(returnTargets.length > 0 ? { target_seq: returnTarget ?? returnTargets[0]?.seq } : {}),
      });
      message.success(t('comp.flow.rejected'));
      setRejectOpen(false);
      setRejectReason('');
      setReturnTarget(undefined);
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
        {isApproval && (
          <>
            <Button type="primary" icon={<CheckOutlined />} onClick={() => setApprovalOpen(true)}>
              {t('comp.flow.approve')}
            </Button>
            <Button
              danger
              icon={<CloseOutlined />}
              onClick={() => {
                setReturnTarget(returnTargets[0]?.seq);
                setRejectOpen(true);
              }}
            >
              {t('comp.flow.reject')}
            </Button>
          </>
        )}
        <ProcessReassignButton step={step} onDone={onDone} />
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
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          {returnTargets.length > 0 && (
            <div>
              <Typography.Text strong>{t('comp.flow.returnTarget')}</Typography.Text>
              <Select
                style={{ width: '100%', marginTop: 6 }}
                value={returnTarget}
                onChange={setReturnTarget}
                options={returnTargets.map((target) => ({ value: target.seq, label: target.name }))}
              />
            </div>
          )}
          <Input.TextArea
            rows={4}
            maxLength={500}
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            placeholder={t('comp.flow.rejectReasonPlaceholder')}
          />
        </Space>
      </Modal>
    </>
  );
}
