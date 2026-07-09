import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Badge, Button, Empty, List, Popover, Typography } from 'antd';
import { BellOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from '../api/client';
import type { NotificationItem } from '../api/types';

export default function NotificationBell() {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    try {
      const data = await api.get<NotificationItem[]>('/notifications');
      setItems(data ?? []);
    } catch {
      // 错误已由 api client 统一提示
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const unread = items.filter((i) => !i.read_at).length;

  const handleClick = async (item: NotificationItem) => {
    try {
      if (!item.read_at) {
        await api.post(`/notifications/${item.id}/read`);
        setItems((prev) =>
          prev.map((i) => (i.id === item.id ? { ...i, read_at: new Date().toISOString() } : i)),
        );
      }
    } catch {
      // 忽略，已统一提示
    }
    setOpen(false);
    if (item.link) navigate(item.link);
  };

  const content = (
    <div style={{ width: 320, maxHeight: 400, overflowY: 'auto' }}>
      {items.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无通知" />
      ) : (
        <List
          size="small"
          dataSource={items}
          renderItem={(item) => (
            <List.Item
              style={{ cursor: 'pointer' }}
              onClick={() => void handleClick(item)}
            >
              <List.Item.Meta
                title={
                  <Typography.Text strong={!item.read_at}>{item.title}</Typography.Text>
                }
                description={
                  <>
                    <Typography.Paragraph
                      type="secondary"
                      ellipsis={{ rows: 2 }}
                      style={{ marginBottom: 4 }}
                    >
                      {item.content}
                    </Typography.Paragraph>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {dayjs(item.created_at).format('YYYY-MM-DD HH:mm')}
                    </Typography.Text>
                  </>
                }
              />
            </List.Item>
          )}
        />
      )}
    </div>
  );

  return (
    <Popover
      title="通知"
      trigger="click"
      placement="bottomRight"
      content={content}
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (v) void load();
      }}
    >
      <Badge count={unread} size="small">
        <Button type="text" icon={<BellOutlined style={{ fontSize: 18 }} />} />
      </Badge>
    </Popover>
  );
}
