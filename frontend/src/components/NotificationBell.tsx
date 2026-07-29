import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Badge, Button, Empty, List, Popover, Typography } from 'antd';
import { BellOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from '../api/client';
import type { NotificationItem } from '../api/types';
import { useT } from '../i18n';

export default function NotificationBell() {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const t = useT();

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
    // M34：60s 轮询未读（仅页面可见时），管理员无需刷新即可看到开通申请等新通知
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') void load();
    }, 60_000);
    const onVisible = () => {
      if (document.visibilityState === 'visible') void load();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [load]);

  const unread = items.filter((i) => !i.read_at).length;

  const handleMarkAllRead = async () => {
    if (!unread) return;
    try {
      await api.post<{ updated: number }>('/notifications/read-all');
      const readAt = new Date().toISOString();
      setItems((prev) => prev.map((item) => (item.read_at ? item : { ...item, read_at: readAt })));
    } catch {
      // 忽略，已由 api client 统一提示
    }
  };

  const handleClearRead = async () => {
    try {
      await api.post<{ deleted: number }>('/notifications/clear-read');
      setItems((prev) => prev.filter((item) => !item.read_at));
    } catch {
      // 忽略，已由 api client 统一提示
    }
  };

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
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('header.noNotifications')} />
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

  const popoverTitle = (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
      <Typography.Text strong>{t('header.notifications')}</Typography.Text>
      <span>
        <Button
          type="link"
          size="small"
          disabled={!unread}
          onClick={(event) => {
            event.stopPropagation();
            void handleMarkAllRead();
          }}
        >
          {t('header.markAllRead')}
        </Button>
        <Button
          type="link"
          size="small"
          onClick={(event) => {
            event.stopPropagation();
            void handleClearRead();
          }}
        >
          {t('header.clearRead')}
        </Button>
      </span>
    </div>
  );

  return (
    <Popover
      title={popoverTitle}
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
