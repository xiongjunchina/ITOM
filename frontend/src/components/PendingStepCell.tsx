import { Button, Space, Tag, Typography } from 'antd';
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
 * 列表页「当前节点」单元格（M31/M31.1）：
 * 轮到我处理 → 橙色「待我处理·节点名」+「去处理」进入详情页（看完整上下文后再操作）；
 * 他人处理中 → 灰字节点名·处理人；流程已完/无流程 → '-'。
 */
export default function PendingStepCell({
  pending,
  onGo,
}: {
  pending?: PendingStep | null;
  /** 进入该单据详情页处理 */
  onGo: () => void;
}) {
  const t = useT();

  if (!pending) return <Typography.Text type="secondary">-</Typography.Text>;
  if (!pending.mine) {
    return (
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {pending.name}
        {pending.assignee_name ? ` · ${pending.assignee_name}` : ''}
      </Typography.Text>
    );
  }
  return (
    <Space direction="vertical" size={2}>
      <Tag color="orange" style={{ marginInlineEnd: 0 }}>
        {t('comp.pending.mine', { name: pending.name })}
      </Tag>
      <Button type="link" size="small" style={{ padding: 0 }} onClick={onGo}>
        {t('comp.pending.go')}
      </Button>
    </Space>
  );
}
