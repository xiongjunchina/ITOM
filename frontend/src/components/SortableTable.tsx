import { Button, Card, Checkbox, Divider, Dropdown, Space, Table, Tooltip } from 'antd';
import {
  Children,
  cloneElement,
  isValidElement,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactElement,
  type ReactNode,
} from 'react';
import TableStandardToolbar, { type TableStandardOptions } from './TableStandardToolbar';
import type { ColumnType, ColumnsType, TableProps } from 'antd/es/table';
import {
  CalendarOutlined,
  CheckCircleOutlined,
  CopyOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  EyeOutlined,
  LinkOutlined,
  MoreOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
  SaveOutlined,
  SettingOutlined,
  StarOutlined,
  StopOutlined,
  SwapOutlined,
  UndoOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import { api } from '../api/client';
import { useAuthStore } from '../stores/auth';

type SortableTableProps<T extends object> = TableProps<T> & {
  /**
   * 默认让有 dataIndex 的业务列都可排序；操作列、纯 render 列保持不可排序。
   * 传入 sorter 的列会保留页面自己的比较逻辑。
   */
  autoSort?: boolean;
  /** 可选的统一列表工具栏：关键字、字段过滤、当前数据导出。 */
  standardToolbar?: TableStandardOptions<T>;
  /** 可选的稳定标识；缺省按当前路由隔离清单布局。 */
  tableKey?: string;
  /** 不允许用户隐藏的字段，例如编号、标题和操作列。 */
  requiredColumnKeys?: string[];
};

type ViewConfig = { visible: string[]; widths: Record<string, number> };

const TABLE_VIEW_KEY_PATTERN = /^[a-z][a-z0-9_.-]{1,63}$/;
const MIN_COLUMN_WIDTH = 64;
const MAX_COLUMN_WIDTH = 800;
const MIN_ACTION_COLUMN_WIDTH = 80;
const COMPACT_ACTION_COLUMN_WIDTH = 144;

function sanitizeViewConfig(value: unknown): ViewConfig | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const raw = value as { visible?: unknown; widths?: unknown };
  if (!Array.isArray(raw.visible) || !raw.visible.every((key) => typeof key === 'string')) return null;
  if (!raw.widths || typeof raw.widths !== 'object' || Array.isArray(raw.widths)) return null;
  const widths = Object.fromEntries(
    Object.entries(raw.widths as Record<string, unknown>)
      .filter(([key, width]) => typeof key === 'string' && Number.isFinite(width) && typeof width === 'number')
      .map(([key, width]) => [key, Math.max(MIN_COLUMN_WIDTH, Math.min(MAX_COLUMN_WIDTH, Math.trunc(width as number)))]),
  );
  return { visible: raw.visible, widths };
}

function sanitizeTableViews(value: unknown): Record<string, ViewConfig> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .filter(([key]) => TABLE_VIEW_KEY_PATTERN.test(key))
      .flatMap(([key, config]) => {
        const normalized = sanitizeViewConfig(config);
        return normalized ? [[key, normalized]] : [];
      }),
  );
}

function routeTableKey(path: string): string {
  const normalized = path.replace(/[^a-zA-Z0-9]+/g, '.').replace(/^\.+|\.+$/g, '').toLowerCase();
  return `route.${normalized || 'root'}`;
}

/**
 * 同一路由可能并排渲染多张字段不同的清单（例如总览的两个榜单）。
 * 列集合哈希让它们的个人布局彼此隔离，同时避免把完整字段名拼进偏好键。
 */
function tableSchemaKey(columnKeys: string[]): string {
  let hash = 2166136261;
  for (const char of columnKeys.slice().sort().join('|')) {
    hash ^= char.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

function columnKey<T extends object>(column: ColumnType<T>, index: string | number): string {
  if (column.key != null) return String(column.key);
  if (column.dataIndex != null) return Array.isArray(column.dataIndex) ? column.dataIndex.join('.') : String(column.dataIndex);
  return `column-${index}`;
}

function leafColumns<T extends object>(columns: ColumnsType<T>, prefix = ''): Array<{ column: ColumnType<T>; key: string }> {
  const result: Array<{ column: ColumnType<T>; key: string }> = [];
  columns.forEach((column, index) => {
    if ('children' in column && column.children) {
      result.push(...leafColumns(column.children, `${prefix}${index}.`));
    } else {
      result.push({ column: column as ColumnType<T>, key: columnKey(column as ColumnType<T>, `${prefix}${index}`) });
    }
  });
  return result;
}

function defaultColumnWidth<T extends object>(column: ColumnType<T>): number {
  if (typeof column.width === 'number' && Number.isFinite(column.width)) {
    return Math.max(MIN_COLUMN_WIDTH, Math.min(MAX_COLUMN_WIDTH, Math.round(column.width)));
  }
  // 旧页面未设置 width 时也必须可以拖拽；160px 是密集业务清单的中性起点。
  return 160;
}

function compactActionColumnWidth<T extends object>(column: ColumnType<T>): number {
  const declared = typeof column.width === 'number' && Number.isFinite(column.width)
    ? Math.round(column.width)
    : COMPACT_ACTION_COLUMN_WIDTH;
  return Math.max(MIN_ACTION_COLUMN_WIDTH, Math.min(COMPACT_ACTION_COLUMN_WIDTH, declared));
}

function ResizableHeaderCell(props: Record<string, unknown>) {
  const { children, className, onResize, onResizeEnd, onResizeStep, width, ...rest } = props as {
    children?: ReactNode;
    className?: string;
    onResize?: (width: number) => void;
    onResizeEnd?: (width: number) => void;
    onResizeStep?: (delta: number) => void;
    width?: number;
    [key: string]: unknown;
  };
  // 不能把拖拽状态放在闭包局部变量中：拖动时 setViewConfig 会触发表格重渲染，
  // 局部变量会被重置，视觉上就会表现为“拖不动”。保留 Pointer Events 以支持触控，
  // 同时保留 Mouse Events 回退，兼容部分浏览器、嵌入式环境和自动化工具只派发鼠标事件的情形。
  const dragRef = useRef<{
    kind: 'pointer' | 'mouse';
    pointerId?: number;
    startX: number;
    startWidth: number;
    lastWidth: number;
    columnElements: HTMLTableColElement[];
  } | null>(null);
  const priorCursorRef = useRef('');
  const mouseListenersRef = useRef<{ move: (event: MouseEvent) => void; up: () => void } | null>(null);
  const restoreCursor = () => {
    document.body.style.cursor = priorCursorRef.current;
  };
  const clearMouseListeners = () => {
    const listeners = mouseListenersRef.current;
    if (!listeners) return;
    document.removeEventListener('mousemove', listeners.move);
    document.removeEventListener('mouseup', listeners.up);
    mouseListenersRef.current = null;
  };
  const finishResize = () => {
    const drag = dragRef.current;
    if (!drag) return;
    clearMouseListeners();
    dragRef.current = null;
    restoreCursor();
    // 连续拖动期间不能每个 mousemove 都 setState：固定列、展开列或 sticky
    // 表头在 Ant Design 重建时会卸载当前 header cell，进而取消本次拖动。松开时
    // 一次性把最终宽度交给 React 和偏好保存，直接 DOM 更新只负责拖动中的视觉反馈。
    if (drag.lastWidth !== drag.startWidth) {
      onResize?.(drag.lastWidth);
      onResizeEnd?.(drag.lastWidth);
    }
  };
  useEffect(() => () => {
    if (!dragRef.current) return;
    clearMouseListeners();
    dragRef.current = null;
    restoreCursor();
  }, []);
  const columnElementsFor = (handle: HTMLSpanElement): HTMLTableColElement[] => {
    const headerCell = handle.closest('th');
    if (!headerCell) return [];
    const columnIndex = headerCell.cellIndex;
    const tableRoot = headerCell.closest('.ant-table-container') ?? headerCell.closest('.ant-table') ?? headerCell.closest('table');
    const tables = tableRoot instanceof HTMLTableElement
      ? [tableRoot]
      : Array.from(tableRoot?.querySelectorAll('table') ?? []);
    return tables.flatMap((table) => {
      const column = table.querySelectorAll<HTMLTableColElement>('colgroup col')[columnIndex];
      return column ? [column] : [];
    });
  };
  const beginResize = (
    kind: 'pointer' | 'mouse',
    startX: number,
    startWidth: number,
    handle: HTMLSpanElement,
    pointerId?: number,
  ) => {
    if (dragRef.current) return false;
    dragRef.current = {
      kind,
      pointerId,
      startX,
      startWidth,
      lastWidth: startWidth,
      columnElements: columnElementsFor(handle),
    };
    priorCursorRef.current = document.body.style.cursor;
    document.body.style.cursor = 'col-resize';
    return true;
  };
  const applyResize = (clientX: number) => {
    const drag = dragRef.current;
    if (!drag) return;
    const nextWidth = Math.max(MIN_COLUMN_WIDTH, Math.min(MAX_COLUMN_WIDTH, drag.startWidth + clientX - drag.startX));
    drag.lastWidth = nextWidth;
    drag.columnElements.forEach((column) => {
      column.style.width = `${nextWidth}px`;
    });
  };
  const startPointerResize = (event: ReactPointerEvent<HTMLSpanElement>) => {
    if (event.button !== 0 || !event.isPrimary) return;
    event.preventDefault();
    event.stopPropagation();
    if (!beginResize('pointer', event.clientX, width ?? MIN_COLUMN_WIDTH, event.currentTarget, event.pointerId)) return;
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const resizePointer = (event: ReactPointerEvent<HTMLSpanElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.kind !== 'pointer' || drag.pointerId !== event.pointerId) return;
    event.preventDefault();
    applyResize(event.clientX);
  };
  const stopPointerResize = (event: ReactPointerEvent<HTMLSpanElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.kind !== 'pointer' || drag.pointerId !== event.pointerId) return;
    event.preventDefault();
    finishResize();
  };
  const startMouseResize = (event: ReactMouseEvent<HTMLSpanElement>) => {
    if (event.button !== 0 || !onResize || !width) return;
    event.preventDefault();
    event.stopPropagation();
    // Chrome 会在部分 Pointer Events 序列后继续派发兼容 mousedown。此时不要
    // 覆盖已有的 pointer 状态，但要补挂 document 级 mousemove/mouseup，避免
    // 指针按下已送达、移动事件却只以 mousemove 形式到达时仍然“拖不动”。
    if (!dragRef.current && !beginResize('mouse', event.clientX, width, event.currentTarget)) return;
    if (mouseListenersRef.current) return;
    const move = (moveEvent: MouseEvent) => {
      if (!dragRef.current) return;
      moveEvent.preventDefault();
      applyResize(moveEvent.clientX);
    };
    const up = () => finishResize();
    mouseListenersRef.current = { move, up };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up, { once: true });
  };
  if (!onResize || !width) return <th {...rest}>{children}</th>;
  return (
    <th {...rest} className={`${className ?? ''} sortable-table__header-cell`} style={{ ...(rest.style as CSSProperties | undefined), position: 'relative' }}>
      {children}
      <span
        className="sortable-table__column-resize-handle"
        role="separator"
        aria-label="调整列宽"
        aria-orientation="vertical"
        title="拖动调整列宽"
        tabIndex={0}
        onPointerDown={startPointerResize}
        onPointerMove={resizePointer}
        onPointerUp={stopPointerResize}
        onPointerCancel={stopPointerResize}
        onLostPointerCapture={stopPointerResize}
        onMouseDown={startMouseResize}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
        }}
        onKeyDown={(event) => {
          if (event.key === 'ArrowLeft') {
            event.preventDefault();
            onResizeStep?.(-16);
          } else if (event.key === 'ArrowRight') {
            event.preventDefault();
            onResizeStep?.(16);
          }
        }}
      />
    </th>
  );
}

function valueAt<T extends object>(record: T, dataIndex: ColumnType<T>['dataIndex']): unknown {
  if (dataIndex == null) return undefined;
  const path = Array.isArray(dataIndex) ? dataIndex : [dataIndex];
  return path.reduce<unknown>((value, key) => {
    if (value == null || typeof value !== 'object') return undefined;
    return (value as Record<string | number, unknown>)[key as string | number];
  }, record);
}

function compareValues(left: unknown, right: unknown): number {
  if (left == null && right == null) return 0;
  if (left == null) return 1;
  if (right == null) return -1;
  if (typeof left === 'number' && typeof right === 'number') return left - right;
  if (typeof left === 'boolean' && typeof right === 'boolean') return Number(left) - Number(right);
  const leftText = String(left);
  const rightText = String(right);
  const leftNumber = Number(leftText.replace(/[% ,]/g, ''));
  const rightNumber = Number(rightText.replace(/[% ,]/g, ''));
  if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) return leftNumber - rightNumber;
  return leftText.localeCompare(rightText, ['zh-CN', 'en'], { numeric: true, sensitivity: 'base' });
}

function augmentColumns<T extends object>(columns: ColumnsType<T>): ColumnsType<T> {
  return columns.map((column) => {
    if ('children' in column && column.children) {
      return { ...column, children: augmentColumns(column.children) };
    }
    const source = column as ColumnType<T>;
    // 部分业务列使用 key 代替 dataIndex（例如后端返回的派生字段），只要 key
    // 是普通字段名同样应支持点击表头排序；操作列明确排除。
    const sortableKey = source.dataIndex ?? (
      typeof source.key === 'string' || typeof source.key === 'number' ? source.key : undefined
    );
    if (source.sorter || sortableKey == null || source.key === 'action' || source.key === 'actions') return source;
    return {
      ...source,
      sorter: (left: T, right: T) => compareValues(valueAt(left, sortableKey), valueAt(right, sortableKey)),
      sortDirections: ['ascend', 'descend'] as const,
    };
  });
}

type ActionElementProps = {
  children?: ReactNode;
  className?: string;
  icon?: ReactNode;
  title?: ReactNode;
  'aria-label'?: string;
  onClick?: unknown;
  href?: unknown;
  to?: unknown;
};

function nodeText(node: unknown): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node).trim();
  if (Array.isArray(node)) return node.map(nodeText).filter(Boolean).join(' ').trim();
  if (isValidElement<ActionElementProps>(node)) return nodeText(node.props.children);
  return '';
}

function isActionColumn<T extends object>(column: ColumnType<T>, key: string): boolean {
  const dataIndex = Array.isArray(column.dataIndex) ? column.dataIndex.join('.') : String(column.dataIndex ?? '');
  const normalized = `${key}|${dataIndex}`.toLocaleLowerCase();
  const title = nodeText(column.title).toLocaleLowerCase();
  return ['action', 'actions', 'operation', 'operations'].some((token) => normalized.split('|').includes(token))
    || ['操作', '操作项', 'actions', 'action', 'operations', 'operation'].includes(title);
}

function actionIcon(label: string): ReactNode {
  const normalized = label.toLocaleLowerCase();
  if (/重新|重开|恢复|继续|reopen|restart|resume/.test(normalized)) return <ReloadOutlined />;
  if (/详情|查看|预览|detail|view|preview/.test(normalized)) return <EyeOutlined />;
  if (/编辑|修改|edit|modify/.test(normalized)) return <EditOutlined />;
  if (/删除|移除|delete|remove/.test(normalized)) return <DeleteOutlined />;
  if (/暂停|pause/.test(normalized)) return <PauseCircleOutlined />;
  if (/关闭|完成|确认|close|complete|confirm/.test(normalized)) return <CheckCircleOutlined />;
  if (/执行|开始|受理|启用|run|start|accept|enable/.test(normalized)) return <PlayCircleOutlined />;
  if (/排期|日程|schedule|calendar/.test(normalized)) return <CalendarOutlined />;
  if (/中止|终止|停用|abort|terminate|disable|stop/.test(normalized)) return <StopOutlined />;
  if (/新增|添加|创建|加子任务|add|create|new/.test(normalized)) return <PlusOutlined />;
  if (/导入|上传|import|upload/.test(normalized)) return <UploadOutlined />;
  if (/导出|下载|export|download/.test(normalized)) return <DownloadOutlined />;
  if (/转派|改派|指派|调整|移动|transfer|assign|move/.test(normalized)) return <SwapOutlined />;
  if (/关联|链接|link|relate/.test(normalized)) return <LinkOutlined />;
  if (/驳回|退回|撤回|reject|return|withdraw/.test(normalized)) return <UndoOutlined />;
  if (/复制|copy/.test(normalized)) return <CopyOutlined />;
  if (/评价|评分|审核|rate|review|score/.test(normalized)) return <StarOutlined />;
  if (/保存|提交|save|submit/.test(normalized)) return <SaveOutlined />;
  return <MoreOutlined />;
}

function iconifyActionNode(node: ReactNode, insideTooltip = false): ReactNode {
  if (node == null || typeof node === 'boolean') return node;
  if (Array.isArray(node)) return node.map((child) => iconifyActionNode(child, insideTooltip));
  if (!isValidElement<ActionElementProps>(node)) return node;

  const element = node as ReactElement<ActionElementProps>;
  const isTooltip = element.type === Tooltip;
  if (isTooltip) {
    return cloneElement(element, undefined, Children.map(element.props.children, (child) => iconifyActionNode(child, true)));
  }

  const children = Children.map(element.props.children, (child) => iconifyActionNode(child, insideTooltip));
  const label = nodeText(element.props.children) || nodeText(element.props.title) || element.props['aria-label'] || '';
  const isControl = Boolean(element.props.onClick || element.props.href || element.props.to)
    || element.type === Button
    || element.type === 'a';
  if (!isControl || !label) return cloneElement(element, undefined, children);

  const className = [element.props.className, 'sortable-table__action-icon-button'].filter(Boolean).join(' ');
  const converted = cloneElement(element, {
    className,
    icon: element.type === Button ? (element.props.icon ?? actionIcon(label)) : element.props.icon,
    title: element.type === 'a' ? label : element.props.title,
    'aria-label': element.props['aria-label'] ?? label,
  }, element.type === Button ? null : actionIcon(label));
  return insideTooltip ? converted : <Tooltip title={label}>{converted}</Tooltip>;
}

function iconifyActionRender(rendered: unknown): unknown {
  if (
    rendered
    && typeof rendered === 'object'
    && !isValidElement(rendered)
    && 'children' in rendered
  ) {
    const descriptor = rendered as { children: ReactNode; props?: Record<string, unknown> };
    return { ...descriptor, children: iconifyActionNode(descriptor.children) };
  }
  return iconifyActionNode(rendered as ReactNode);
}

/**
 * 统一表格排序入口。所有业务表只要使用此组件，表头字段即可点击排序，
 * 并且不会覆盖页面已经定义的自定义 sorter。
 */
export default function SortableTable<T extends object>({ autoSort = true, columns, standardToolbar, dataSource, pagination, tableKey, requiredColumnKeys = [], ...props }: SortableTableProps<T>) {
  const user = useAuthStore((state) => state.user);
  const setUser = useAuthStore((state) => state.setUser);
  const tableAnchorRef = useRef<HTMLDivElement>(null);
  const [appScrollContainer, setAppScrollContainer] = useState<HTMLElement | null>(null);
  useLayoutEffect(() => {
    // MainLayout 不是由 window 滚动，而是由固定高度的 .app-content 滚动。
    // Ant Design 的 sticky 若仍绑定 window，会同时导致表头无法吸顶、底部横向
    // 滚动条离开当前可视区域。统一在业务清单入口绑定真实滚动容器。
    setAppScrollContainer(tableAnchorRef.current?.closest<HTMLElement>('.app-content') ?? null);
  }, []);
  const resolvedSticky = useMemo<TableProps<T>['sticky']>(() => {
    if (props.sticky === false) return false;
    if (typeof props.sticky === 'object') {
      return {
        ...props.sticky,
        getContainer: props.sticky.getContainer ?? (() => appScrollContainer ?? window),
      };
    }
    // 主页面的所有统一业务清单默认固定表头；Drawer/Modal 等不在 app-content
    // 内的表格保持原行为，除非页面显式传入 sticky。
    if (appScrollContainer) {
      return { offsetHeader: 0, getContainer: () => appScrollContainer };
    }
    return props.sticky;
  }, [appScrollContainer, props.sticky]);
  const leaves = useMemo(() => leafColumns(columns ?? []), [columns]);
  const knownKeys = useMemo(() => leaves.map((item) => item.key), [leaves]);
  const legacyTableKey = tableKey ?? routeTableKey(window.location.pathname);
  const resolvedTableKey = tableKey ?? `${legacyTableKey.slice(0, 54)}.${tableSchemaKey(knownKeys)}`;
  const protectedKeys = useMemo(
    () => new Set(requiredColumnKeys.concat(leaves.filter(({ column }) => column.fixed === 'left' || column.fixed === 'right' || column.key === 'action' || column.key === 'actions').map(({ key }) => key))),
    [leaves, requiredColumnKeys],
  );
  const defaultConfig = useMemo<ViewConfig>(() => ({
    visible: knownKeys,
    widths: Object.fromEntries(leaves.map(({ column, key }) => [
      key,
      isActionColumn(column, key) ? compactActionColumnWidth(column) : defaultColumnWidth(column),
    ])),
  }), [knownKeys, leaves]);
  const [viewConfig, setViewConfig] = useState<ViewConfig>(defaultConfig);
  const viewConfigRef = useRef(viewConfig);
  useEffect(() => {
    viewConfigRef.current = viewConfig;
  }, [viewConfig]);

  useEffect(() => {
    const storedViews = user?.preferences?.table_views;
    // 兼容本次修复前仅按路由保存的布局；首次再次保存时迁移到列集合隔离键。
    const saved = sanitizeViewConfig(storedViews?.[resolvedTableKey])
      ?? (resolvedTableKey === legacyTableKey ? null : sanitizeViewConfig(storedViews?.[legacyTableKey]));
    const savedVisible = saved?.visible.filter((key) => knownKeys.includes(key)) ?? [];
    const visible = saved ? savedVisible : knownKeys;
    setViewConfig({
      visible: Array.from(new Set([...visible, ...Array.from(protectedKeys).filter((key) => knownKeys.includes(key))])),
      widths: { ...defaultConfig.widths, ...(saved?.widths ?? {}) },
    });
  }, [defaultConfig, knownKeys, legacyTableKey, protectedKeys, resolvedTableKey, user?.preferences?.table_views]);

  const persistViewConfig = async (next: ViewConfig) => {
    viewConfigRef.current = next;
    setViewConfig(next);
    if (!user) return;
    const tableViews = { ...sanitizeTableViews(user.preferences?.table_views), [resolvedTableKey]: next };
    if (resolvedTableKey !== legacyTableKey) delete tableViews[legacyTableKey];
    try {
      await api.patch('/auth/me/preferences', { table_views: tableViews });
      setUser({ ...user, preferences: { ...user.preferences, table_views: tableViews } });
    } catch {
      // 已统一提示；本地布局仍保留，下一次加载时以后端配置为准。
    }
  };

  const configuredColumns = useMemo(() => {
    const transform = (sourceColumns: ColumnsType<T>, prefix = ''): ColumnsType<T> => {
      const result: ColumnsType<T> = [];
      sourceColumns.forEach((column, index) => {
        if ('children' in column && column.children) {
          const children = transform(column.children, `${prefix}${index}.`);
          if (children.length) result.push({ ...column, children });
          return;
        }
        const source = column as ColumnType<T>;
        const key = columnKey(source, `${prefix}${index}`);
        if (!viewConfig.visible.includes(key) && !protectedKeys.has(key)) return;
        const actionColumn = isActionColumn(source, key);
        // 操作列沿用页面声明的紧凑宽度，并统一限制在 80-144px；这样既能容纳
        // 页面实际操作数量，也不会被历史偏好或通用默认值撑出大块空白。
        const width = actionColumn
          ? compactActionColumnWidth(source)
          : (viewConfig.widths[key] ?? defaultColumnWidth(source));
        const render = source.render && actionColumn
          ? ((value: unknown, record: T, renderIndex: number) => iconifyActionRender(source.render!(value, record, renderIndex))) as ColumnType<T>['render']
          : source.render;
        result.push({
          ...source,
          render,
          width,
          className: [typeof source.className === 'string' ? source.className : '', actionColumn ? 'sortable-table__action-cell' : '']
            .filter(Boolean)
            .join(' '),
          onHeaderCell: (headerColumn) => ({
            ...(source.onHeaderCell?.(headerColumn) ?? {}),
            width,
            ...(actionColumn ? {} : {
              onResize: (nextWidth: number) => {
                const next = { ...viewConfigRef.current, widths: { ...viewConfigRef.current.widths, [key]: nextWidth } };
                viewConfigRef.current = next;
                setViewConfig(next);
              },
              onResizeEnd: () => void persistViewConfig(viewConfigRef.current),
              onResizeStep: (delta: number) => {
                const nextWidth = Math.max(MIN_COLUMN_WIDTH, Math.min(MAX_COLUMN_WIDTH, width + delta));
                void persistViewConfig({ ...viewConfigRef.current, widths: { ...viewConfigRef.current.widths, [key]: nextWidth } });
              },
            }),
          }),
        } as ColumnType<T>);
      });
      return result;
    };
    return transform(columns ?? []);
  }, [columns, protectedKeys, viewConfig]);
  const tableColumnsWithView = autoSort && configuredColumns ? augmentColumns(configuredColumns) : configuredColumns;
  const rows = (dataSource ?? []) as T[];
  const [query, setQuery] = useState('');
  const [filterField, setFilterField] = useState<string>();
  const [filterValue, setFilterValue] = useState<string>();
  const filteredRows = useMemo(() => {
    if (!standardToolbar) return rows;
    const fields = standardToolbar.searchFields?.map(String);
    const searchable = augmentColumns(columns ?? [])
      .flatMap((column) => 'children' in column && column.children ? column.children : [column])
      .map((column) => column as ColumnType<T>)
      .filter((column) => column.dataIndex != null)
      .filter((column) => !fields || fields.includes(Array.isArray(column.dataIndex) ? column.dataIndex.join('.') : String(column.dataIndex)));
    const normalized = query.trim().toLocaleLowerCase();
    return rows.filter((row) => {
      const matchesQuery = !normalized || searchable.some((column) => String(valueAt(row, column.dataIndex) ?? '').toLocaleLowerCase().includes(normalized));
      const matchesFilter = !filterField || !filterValue || String(valueAt(row, filterField as ColumnType<T>['dataIndex']) ?? '') === filterValue;
      return matchesQuery && matchesFilter;
    });
  }, [columns, filterField, filterValue, query, rows, standardToolbar]);
  const tablePagination = standardToolbar && pagination && typeof pagination === 'object'
    ? {
      ...pagination,
      // 服务端分页的页面已传入真实 total；不能用当前页 rows 的长度覆盖它，
      // 否则所有使用统一工具栏的远程清单都会把“共 46 条”错误显示为“共 20 条”。
      // 未传 total 的本地全量清单才由组件按本地筛选结果计算。
      ...(pagination.total == null ? { total: filteredRows.length } : {}),
      // 筛选结果可能少于当前页，强制回到第一页，避免出现“有结果但当前页为空”。
      current: query.trim() || filterField || filterValue ? 1 : pagination.current,
    }
    : pagination;
  const toolbarTotal = standardToolbar?.total ?? (
    pagination && typeof pagination === 'object' ? pagination.total : undefined
  );
  // WBS 等专用宽表已提供自己的表头组件和本地布局逻辑；不能由通用组件
  // 再次覆盖，否则其拖拽回调会被截断。普通业务清单则使用统一表头单元格。
  const headerCell = props.components?.header?.cell ?? ResizableHeaderCell;
  return (
    <>
      <Space direction="vertical" style={{ width: '100%' }} size={8}>
        {standardToolbar && (
          <TableStandardToolbar
            options={{ ...standardToolbar, total: toolbarTotal }}
            columns={columns ?? []}
            rows={rows}
            filteredRows={filteredRows}
            query={query}
            onQueryChange={setQuery}
            filterField={filterField}
            filterValue={filterValue}
            onFilterFieldChange={setFilterField}
            onFilterValueChange={setFilterValue}
          />
        )}
        <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
          <Dropdown
            trigger={['click']}
            dropdownRender={() => (
              <Card size="small" title="显示字段" style={{ width: 260 }}>
                <Checkbox.Group
                  style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
                  value={viewConfig.visible}
                  options={leaves.map(({ column, key }) => ({
                    value: key,
                    label: typeof column.title === 'string' ? column.title : key,
                    disabled: protectedKeys.has(key),
                  }))}
                  onChange={(values) => void persistViewConfig({ ...viewConfig, visible: Array.from(new Set([...values.map(String), ...Array.from(protectedKeys)])) })}
                />
                <Divider style={{ margin: '12px 0' }} />
                <Button size="small" onClick={() => void persistViewConfig(defaultConfig)}>恢复默认</Button>
              </Card>
            )}
          >
            <Tooltip title="配置显示字段和列宽"><Button icon={<SettingOutlined />}>列设置</Button></Tooltip>
          </Dropdown>
        </Space>
        <div ref={tableAnchorRef} className="sortable-table__viewport-anchor">
          <Table<T>
            {...props}
            columns={tableColumnsWithView}
            dataSource={standardToolbar ? filteredRows : dataSource}
            pagination={tablePagination}
            scroll={{ x: 'max-content', ...(props.scroll ?? {}) }}
            sticky={resolvedSticky}
            // 明确固定布局，列宽状态变化才会同步应用到 colgroup，而不是被单元格
            // 内容重新撑回原宽度。
            tableLayout={props.tableLayout ?? 'fixed'}
            components={{ ...(props.components ?? {}), header: { ...(props.components?.header ?? {}), cell: headerCell } }}
          />
        </div>
      </Space>
    </>
  );
}
