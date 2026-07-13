import { useMemo, useState } from 'react';
import type { CSSProperties, DragEvent, ReactNode } from 'react';
import { Button, Drawer, List, Space, Switch, Typography, message } from 'antd';
import { HolderOutlined } from '@ant-design/icons';
import { api } from '../api/client';
import { useAuthStore } from '../stores/auth';
import { useT } from '../i18n';
import type { UserPreferences } from '../api/types';

/** widget 注册项（页面各自维护注册表，key 有序持久化在个人偏好） */
export interface WidgetMeta {
  key: string;
  name: string;
  icon?: ReactNode;
}

/** 铺在 widget 外层容器上的原生拖拽属性（整卡可拖 + 拖经目标描边提示） */
export interface WidgetDragProps {
  draggable: boolean;
  onDragStart: (e: DragEvent<HTMLDivElement>) => void;
  onDragEnd: () => void;
  onDragOver: (e: DragEvent<HTMLDivElement>) => void;
  onDragLeave: (e: DragEvent<HTMLDivElement>) => void;
  onDrop: (e: DragEvent<HTMLDivElement>) => void;
  style: CSSProperties;
}

/**
 * widget 面板通用逻辑（运营总览 / 团队总览共用）：
 * - 偏好为有序数组：数组顺序即显示顺序；不存在/空数组 = 注册表默认顺序全部显示
 * - 原生 HTML5 拖拽排序：放下立即重排（乐观更新）并 PATCH /auth/me/preferences 持久化
 * - 自定义面板抽屉：勾选=在数组中（勾上追加到末尾，取消移除）；恢复默认=存空数组
 */
export function useWidgetBoard(
  registry: readonly WidgetMeta[],
  prefKey: 'dashboard_widgets' | 'team_overview_widgets',
) {
  const { user, setUser } = useAuthStore();
  const t = useT();
  const registryKeys = useMemo(() => registry.map((w) => w.key), [registry]);

  // 生效顺序：偏好数组过滤掉已下线的 key；空/缺省回退注册表默认序（全显）
  const prefArr = user?.preferences?.[prefKey];
  const baseOrder = useMemo(() => {
    if (!prefArr || prefArr.length === 0) return registryKeys;
    return prefArr.filter((k) => registryKeys.includes(k));
  }, [prefArr, registryKeys]);

  // 拖放后的乐观顺序：PATCH 成功把服务端偏好写回 store 后清除；失败清除即回退
  const [optimistic, setOptimistic] = useState<string[] | null>(null);
  const orderedKeys = optimistic ?? baseOrder;

  const [draggingKey, setDraggingKey] = useState<string | null>(null);
  const [overKey, setOverKey] = useState<string | null>(null);

  // 自定义面板抽屉
  const [customOpen, setCustomOpen] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [prefSaving, setPrefSaving] = useState(false);

  const patchPrefs = async (keys: string[]) => {
    const res = await api.patch<{ preferences: UserPreferences }>('/auth/me/preferences', {
      [prefKey]: keys,
    });
    const current = useAuthStore.getState().user;
    if (current) setUser({ ...current, preferences: res.preferences });
  };

  /** 拖放重排：source 移到 target 原来的位置，立即重排并持久化 */
  const dropTo = async (targetKey: string, sourceKey: string) => {
    if (sourceKey === targetKey) return;
    const fromIdx = orderedKeys.indexOf(sourceKey);
    const toIdx = orderedKeys.indexOf(targetKey);
    if (fromIdx < 0 || toIdx < 0) return;
    const next = [...orderedKeys];
    next.splice(fromIdx, 1);
    next.splice(toIdx, 0, sourceKey);
    setOptimistic(next);
    try {
      // 偏好原本为空（=全显默认序）时，这里写入的就是完整注册表的新顺序
      await patchPrefs(next);
      message.success(t('comp.layoutSaved'));
    } catch {
      // 已统一提示；清除乐观顺序即回退服务端顺序
    } finally {
      setOptimistic(null);
    }
  };

  const dragProps = (key: string): WidgetDragProps => ({
    draggable: true,
    onDragStart: (e) => {
      setDraggingKey(key);
      e.dataTransfer.setData('text/plain', key);
      e.dataTransfer.effectAllowed = 'move';
    },
    onDragEnd: () => {
      setDraggingKey(null);
      setOverKey(null);
    },
    onDragOver: (e) => {
      // preventDefault 后才能成为合法放置目标
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      setOverKey(key);
    },
    onDragLeave: (e) => {
      // 移入子元素也会触发 leave：仅在真正离开容器时清除高亮
      if (e.relatedTarget instanceof Node && e.currentTarget.contains(e.relatedTarget)) return;
      setOverKey((prev) => (prev === key ? null : prev));
    },
    onDrop: (e) => {
      e.preventDefault();
      const source = e.dataTransfer.getData('text/plain') || draggingKey;
      setDraggingKey(null);
      setOverKey(null);
      if (source) void dropTo(key, source);
    },
    style: {
      height: '100%',
      borderRadius: 8,
      opacity: draggingKey === key ? 0.45 : undefined,
      outline:
        draggingKey && draggingKey !== key && overKey === key ? '2px dashed #1677ff' : undefined,
      outlineOffset: 2,
    },
  });

  const openCustomize = () => {
    // 勾选状态 = 是否在生效数组中；顺序沿用当前显示顺序
    setSelected([...orderedKeys]);
    setCustomOpen(true);
  };

  /** 勾上追加到数组末尾；取消从数组移除 */
  const toggleSelected = (key: string, checked: boolean) => {
    setSelected((prev) => (checked ? [...prev, key] : prev.filter((k) => k !== key)));
  };

  const saveSelected = async (keys?: string[]) => {
    const list = keys ?? selected;
    // 与注册表默认完全一致（全选且未调序）→ 存空数组：后续新增板块对该用户自动可见
    const isDefault =
      list.length === registryKeys.length && list.every((k, i) => k === registryKeys[i]);
    setPrefSaving(true);
    try {
      await patchPrefs(isDefault ? [] : list);
      message.success(t('comp.panelSaved'));
      setCustomOpen(false);
    } catch {
      // 已统一提示
    } finally {
      setPrefSaving(false);
    }
  };

  /** 恢复默认：清空（存空数组 = 注册表默认顺序全部显示） */
  const resetDefault = () => saveSelected([...registryKeys]);

  return {
    registry,
    orderedKeys,
    dragProps,
    customOpen,
    openCustomize,
    closeCustomize: () => setCustomOpen(false),
    selected,
    toggleSelected,
    saveSelected,
    resetDefault,
    prefSaving,
  };
}

export type WidgetBoard = ReturnType<typeof useWidgetBoard>;

/** widget 卡片标题：拖拽视觉手柄（HolderOutlined + grab 光标）+ 图标 + 名称 */
export function WidgetTitle({ widget, suffix }: { widget: WidgetMeta; suffix?: ReactNode }) {
  return (
    <Space size={8} style={{ cursor: 'grab' }}>
      <HolderOutlined style={{ color: 'rgba(0, 0, 0, 0.45)' }} />
      {widget.icon}
      <span>
        {widget.name}
        {suffix}
      </span>
    </Space>
  );
}

/** 自定义面板抽屉（显隐开关 + 恢复默认），两个总览页共用 */
export function WidgetBoardDrawer({
  board,
  description,
}: {
  board: WidgetBoard;
  description: string;
}) {
  const t = useT();
  return (
    <Drawer
      title={t('comp.customPanel')}
      width={360}
      open={board.customOpen}
      onClose={board.closeCustomize}
      extra={
        <Button
          type="primary"
          loading={board.prefSaving}
          disabled={board.selected.length === 0}
          onClick={() => void board.saveSelected()}
        >
          {t('common.save')}
        </Button>
      }
    >
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        {description}
      </Typography.Paragraph>
      <List
        size="small"
        dataSource={[...board.registry]}
        renderItem={(w) => (
          <List.Item
            actions={[
              <Switch
                key="switch"
                checked={board.selected.includes(w.key)}
                onChange={(checked) => board.toggleSelected(w.key, checked)}
              />,
            ]}
          >
            <Space>
              {w.icon}
              {w.name}
            </Space>
          </List.Item>
        )}
      />
      {board.selected.length === 0 && (
        <Typography.Paragraph type="warning" style={{ fontSize: 12, marginTop: 8 }}>
          {t('comp.keepOne')}
        </Typography.Paragraph>
      )}
      <Button
        block
        style={{ marginTop: 16 }}
        loading={board.prefSaving}
        onClick={() => void board.resetDefault()}
      >
        {t('comp.resetDefault')}
      </Button>
    </Drawer>
  );
}
