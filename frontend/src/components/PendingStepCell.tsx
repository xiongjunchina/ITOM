import { useState } from 'react';
import { Button, Input, Modal, Space, Tag, Typography, message } from 'antd';
import { api } from '../api/client';
import { useT } from '../i18n';

/** 列表行的当前流程节点（M31，后端 pending_steps_map 下发） */
export interface PendingStep {
  task_id: string;
  name: string;
  seq: number | null;
  assignee_name: string | null;
  mine: boolean;
}

/**
 * 列表页「当前节点」单元格（M31）：
 * 轮到我处理 → 橙色「待我处理·节点名」+「完成此步骤」入口（理由弹窗，不必进详情页）；
 * 他人处理中 → 灰字节点名·处理人；流程已完/无流程 → '-'。
 */
export default function PendingStepCell({
  pending,
  onDone,
  extraActions,
}: {
  pending?: PendingStep | null;
  onDone: () => void;
  /** 特殊节点的替代操作（如问题确认节点的 确认/驳回），返回 null 走默认完成按钮 */
  extraActions?: (p: PendingStep) => React.ReactNode | null;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [comment, setComment] = useState('');
  const [saving, setSaving] = useState(false);

  if (!pending) return <Typography.Text type="secondary">-</Typography.Text>;
  if (!pending.mine) {
    return (
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {pending.name}
        {pending.assignee_name ? ` · ${pending.assignee_name}` : ''}
      </Typography.Text>
    );
  }

  const custom = extraActions?.(pending);

  const submit = async () => {
    if (comment.trim().length < 2) {
      message.warning(t('comp.pending.commentRequired'));
      return;
    }
    setSaving(true);
    try {
      await api.post(`/process-tasks/${pending.task_id}/complete`, { comment: comment.trim() });
      message.success(t('itsm.stepDone'));
      setOpen(false);
      setComment('');
      onDone();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  return (
    <Space direction="vertical" size={2}>
      <Tag color="orange" style={{ marginInlineEnd: 0 }}>
        {t('comp.pending.mine', { name: pending.name })}
      </Tag>
      {custom ?? (
        <Button type="link" size="small" style={{ padding: 0 }} onClick={() => setOpen(true)}>
          {t('itsm.completeStep')}
        </Button>
      )}
      <Modal
        title={t('itsm.completeStepTitle', { name: pending.name })}
        open={open}
        confirmLoading={saving}
        onOk={() => void submit()}
        onCancel={() => setOpen(false)}
        destroyOnClose
      >
        <Input.TextArea
          rows={3}
          maxLength={500}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder={t('comp.pending.commentPlaceholder')}
        />
      </Modal>
    </Space>
  );
}
