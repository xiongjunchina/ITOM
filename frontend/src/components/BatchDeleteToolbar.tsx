import { Button, Modal, Space, Typography, message } from 'antd';
import { DeleteOutlined } from '@ant-design/icons';
import type { ReactNode } from 'react';
import { api } from '../api/client';

export interface BatchDeleteResult {
  deleted_ids: string[];
  rejected: Array<{ id: string; code: string; message: string }>;
}

export interface BatchToolbarAction {
  key: string;
  label: ReactNode;
  icon?: ReactNode;
  danger?: boolean;
  disabled?: boolean;
  loading?: boolean;
  onClick: () => void;
}

interface BatchDeleteToolbarProps {
  endpoint?: string;
  selectedIds: string[];
  /** 当删除目标只是当前选择的一部分时，仍显示完整的选择数量。 */
  selectedCount?: number;
  entityName: string;
  onCompleted: () => void;
  actions?: BatchToolbarAction[];
}

/**
 * 仅负责确认、调用与反馈；服务端仍对每条记录执行原有权限、状态、关联和审计校验。
 * 因此批量操作不会成为绕过单条删除规则的入口。
 */
export default function BatchDeleteToolbar({
  endpoint,
  selectedIds,
  selectedCount = selectedIds.length,
  entityName,
  onCompleted,
  actions = [],
}: BatchDeleteToolbarProps) {
  if (selectedCount === 0) return null;

  const confirmDelete = () => {
    Modal.confirm({
      title: `删除已选 ${selectedIds.length} 条${entityName}`,
      content: '系统将逐条校验删除权限、流程状态和关联关系；不符合条件的记录会保留，并在结果中说明原因。',
      okText: '确认删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        if (!endpoint) return;
        const result = await api.delete<BatchDeleteResult>(endpoint, { ids: selectedIds });
        onCompleted();
        if (result.rejected.length === 0) {
          message.success(`已删除 ${result.deleted_ids.length} 条${entityName}`);
          return;
        }
        Modal.info({
          title: '批量删除结果',
          width: 620,
          content: (
            <Space direction="vertical" size={8} style={{ width: '100%', marginTop: 12 }}>
              <Typography.Text>成功删除：{result.deleted_ids.length} 条</Typography.Text>
              <Typography.Text type="warning">未删除：{result.rejected.length} 条</Typography.Text>
              {result.rejected.map((item) => (
                <Typography.Text key={item.id} type="secondary">
                  {item.id}：{item.message}
                </Typography.Text>
              ))}
            </Space>
          ),
        });
      },
    });
  };

  return (
    <div className="batch-operation-toolbar" role="toolbar" aria-label={`${entityName}批量操作`}>
      <Typography.Text strong>已选 {selectedCount} 条</Typography.Text>
      <Space wrap size={8}>
        {actions.map((action) => (
          <Button
            key={action.key}
            icon={action.icon}
            danger={action.danger}
            disabled={action.disabled}
            loading={action.loading}
            onClick={action.onClick}
          >
            {action.label}
          </Button>
        ))}
        {endpoint && selectedIds.length > 0 && (
          <Button danger icon={<DeleteOutlined />} onClick={confirmDelete}>
            删除（{selectedIds.length}）
          </Button>
        )}
      </Space>
    </div>
  );
}
