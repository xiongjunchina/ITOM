import { useState } from 'react';
import { Input, Modal, message } from 'antd';
import { api } from '../api/client';
import { useT } from '../i18n';
import type { FlowDiagramStep } from './FlowDiagram';

/**
 * 完成流程步骤弹窗（项目/需求详情流程卡共用）：
 * 必填阶段结束说明（去空格后 ≥5 字）→ POST /process-tasks/{id}/complete → 推进到下一步骤 → onDone 刷新详情。
 */
export default function CompleteStepModal({
  step,
  onClose,
  onDone,
}: {
  step: FlowDiagramStep | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const t = useT();
  const [comment, setComment] = useState('');
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!step?.task_id) return;
    if (comment.trim().length < 5) {
      message.warning(t('comp.flow.commentRequired'));
      return;
    }
    setSaving(true);
    try {
      await api.post(`/process-tasks/${step.task_id}/complete`, { comment });
      message.success(t('comp.flow.stepDone'));
      setComment('');
      onClose();
      onDone();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={step ? t('comp.flow.completeStepTitle', { name: step.name }) : ''}
      open={!!step}
      onCancel={() => {
        setComment('');
        onClose();
      }}
      onOk={() => void submit()}
      confirmLoading={saving}
      okText={t('common.confirm')}
      cancelText={t('common.cancel')}
    >
      <Input.TextArea
        rows={3}
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        placeholder={t('comp.flow.commentPlaceholder')}
        maxLength={500}
      />
    </Modal>
  );
}
