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
  /** 宽表默认冻结的业务列数；选择框不计入业务列，默认 2。 */
  freezeColumns?: number;
};

type ViewConfig = {
  visible: string[];
  widths: Record<string, number>;
  /** 仅记录用户明确拖拽/键盘调整过的列；其余列随当前数据自动计算。 */
  manual_widths?: string[];
};

const TABLE_VIEW_KEY_PATTERN = /^[a-z][a-z0-9_.-]{1,63}$/;
const MIN_COLUMN_WIDTH = 64;
const MAX_COLUMN_WIDTH = 800;
const MIN_ACTION_COLUMN_WIDTH = 64;
const MAX_ACTION_COLUMN_WIDTH = 176;
const ACTION_ICON_WIDTH = 28;
const ACTION_CELL_PADDING = 8;

function sanitizeViewConfig(value: unknown): ViewConfig | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const raw = value as { visible?: unknown; widths?: unknown; manual_widths?: unknown };
  if (!Array.isArray(raw.visible) || !raw.visible.every((key) => typeof key === 'string')) return null;
  if (!raw.widths || typeof raw.widths !== 'object' || Array.isArray(raw.widths)) return null;
  if (raw.manual_widths != null && (
    !Array.isArray(raw.manual_widths) || !raw.manual_widths.every((key) => typeof key === 'string')
  )) return null;
  const widths = Object.fromEntries(
    Object.entries(raw.widths as Record<string, unknown>)
      .filter(([key, width]) => typeof key === 'string' && Number.isFinite(width) && typeof width === 'number')
      .map(([key, width]) => [key, Math.max(MIN_COLUMN_WIDTH, Math.min(MAX_COLUMN_WIDTH, Math.trunc(width as number)))]),
  );
  return {
    visible: raw.visible,
    widths,
    ...(raw.manual_widths == null ? {} : { manual_widths: Array.from(new Set(raw.manual_widths)) }),
  };
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
    fixedFollowers: Array<{ element: HTMLElement; startLeft: number }>;
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
    // sticky 表头、固定列表头和表体可能由 rc-table 渲染成多张 table。必须从
    // 整个共享 wrapper 收集对应 col，而不能只查当前表头所在 container；否则
    // 拖动时只动表头，表体仍停留在旧宽度，松手前会出现明显错位。
    const tableRoot = headerCell.closest('.ant-table-wrapper') ?? headerCell.closest('.ant-table') ?? headerCell.closest('table');
    const tables = tableRoot instanceof HTMLTableElement
      ? [tableRoot]
      : Array.from(tableRoot?.querySelectorAll('table') ?? []);
    return tables.flatMap((table) => {
      const column = table.querySelectorAll<HTMLTableColElement>('colgroup col')[columnIndex];
      return column ? [column] : [];
    });
  };
  const fixedFollowersFor = (handle: HTMLSpanElement): Array<{ element: HTMLElement; startLeft: number }> => {
    const headerCell = handle.closest('th');
    const tableRoot = headerCell?.closest('.ant-table-wrapper');
    if (!headerCell || !tableRoot || !headerCell.classList.contains('ant-table-cell-fix-left')) return [];
    return Array.from(tableRoot.querySelectorAll<HTMLElement>('.ant-table-cell-fix-left'))
      .filter((cell) => cell instanceof HTMLTableCellElement && cell.cellIndex > headerCell.cellIndex)
      .map((element) => ({ element, startLeft: Number.parseFloat(getComputedStyle(element).left) }))
      .filter(({ startLeft }) => Number.isFinite(startLeft));
  };
  const beginResize = (
    kind: 'pointer' | 'mouse',
    startX: number,
    startWidth: number,
    handle: HTMLSpanElement,
    pointerId?: number,
  ) => {
    if (dragRef.current) return false;
    const renderedWidth = handle.closest('th')?.getBoundingClientRect().width;
    const measuredStartWidth = renderedWidth && Number.isFinite(renderedWidth) ? renderedWidth : startWidth;
    dragRef.current = {
      kind,
      pointerId,
      startX,
      startWidth: measuredStartWidth,
      lastWidth: measuredStartWidth,
      columnElements: columnElementsFor(handle),
      fixedFollowers: fixedFollowersFor(handle),
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
    const delta = nextWidth - drag.startWidth;
    drag.fixedFollowers.forEach(({ element, startLeft }) => {
      element.style.left = `${startLeft + delta}px`;
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
  if (node && typeof node === 'object' && 'children' in node) {
    return nodeText((node as { children?: unknown }).children);
  }
  return '';
}

let tableTextMeasureContext: CanvasRenderingContext2D | null | undefined;

function measuredTextWidth(text: string, weight: 400 | 600 = 400): number {
  if (!text) return 0;
  if (typeof document !== 'undefined') {
    if (tableTextMeasureContext === undefined) {
      tableTextMeasureContext = document.createElement('canvas').getContext('2d');
    }
    if (tableTextMeasureContext) {
      tableTextMeasureContext.font = `${weight} 14px -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`;
      return tableTextMeasureContext.measureText(text).width;
    }
  }
  // 非浏览器构建/测试环境的确定性回退；CJK 按全角、ASCII 按平均字宽估算。
  return Array.from(text).reduce(
    (width, character) => width + (/^[\u2e80-\u9fff\uff01-\uff60]$/.test(character) ? 14 : 8),
    0,
  );
}

function valueText(value: unknown): string {
  if (value == null || value === '') return '';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'bigint') return String(value);
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (value instanceof Date) return value.toISOString();
  if (Array.isArray(value)) return value.map(valueText).filter(Boolean).join(' ');
  return '';
}

/** 首帧先用当前数据估算；挂载后的隐藏 DOM 克隆会再给出真实像素宽度。 */
function estimatedContentColumnWidth<T extends object>(column: ColumnType<T>, rows: T[]): number {
  const headerWidth = measuredTextWidth(nodeText(column.title), 600) + 56;
  const bodyWidth = rows.reduce((maximum, row, index) => {
    const rawValue = valueAt(row, column.dataIndex);
    let renderedText = '';
    let rendered: unknown;
    if (column.render) {
      try {
        rendered = column.render(rawValue, row, index);
        renderedText = nodeText(rendered);
      } catch {
        // 列宽估算不能改变业务 render 的正式错误路径。
      }
    }
    const text = renderedText || valueText(rawValue);
    const visualFallback = rendered != null && !text
      ? defaultColumnWidth(column)
      : 0;
    return Math.max(maximum, measuredTextWidth(text) + 32, visualFallback);
  }, 0);
  return Math.max(MIN_COLUMN_WIDTH, Math.ceil(headerWidth), Math.ceil(bodyWidth));
}

function sameWidths(left: Record<string, number>, right: Record<string, number>): boolean {
  const leftKeys = Object.keys(left);
  const rightKeys = Object.keys(right);
  return leftKeys.length === rightKeys.length
    && leftKeys.every((key) => Math.abs((left[key] ?? 0) - (right[key] ?? 0)) <= 1);
}

/**
 * 从真实表头/表体克隆出不受现有列宽约束的隐藏单元格，批量测量当前渲染内容。
 * 克隆节点不挂事件、不触发请求，只在同一次 layout effect 中存在。
 */
function measureRenderedColumnWidths(anchor: HTMLElement, actionKeys: Set<string>): Record<string, number> {
  const cells = Array.from(anchor.querySelectorAll<HTMLElement>('[data-sortable-column-key]'))
    .filter((cell) => cell.closest('.sortable-table__viewport-anchor') === anchor)
    .filter((cell) => !actionKeys.has(cell.dataset.sortableColumnKey ?? ''));
  if (!cells.length) return {};

  const host = document.createElement('div');
  host.className = 'sortable-table__measure-host';
  const measurements = cells.map((cell) => {
    const clone = cell.cloneNode(true) as HTMLElement;
    clone.querySelectorAll('.sortable-table__column-resize-handle').forEach((handle) => handle.remove());
    clone.classList.remove(
      'ant-table-cell-fix-left',
      'ant-table-cell-fix-left-first',
      'ant-table-cell-fix-left-last',
      'ant-table-cell-fix-right',
      'ant-table-cell-fix-right-first',
      'ant-table-cell-fix-right-last',
      'ant-table-cell-ellipsis',
    );
    clone.style.cssText = [
      'position:static',
      'display:inline-flex',
      'align-items:center',
      'width:max-content',
      'min-width:0',
      'max-width:none',
      'left:auto',
      'right:auto',
      'overflow:visible',
      'text-overflow:clip',
      'white-space:nowrap',
    ].join(';');
    // td/th 脱离 table > tr 后不再命中 Ant Design 的层级 padding 规则；把原
    // 单元格的真实水平 padding 带入克隆，否则每列会被系统性低估约 14px。
    const computed = getComputedStyle(cell);
    clone.style.paddingLeft = computed.paddingLeft;
    clone.style.paddingRight = computed.paddingRight;
    host.appendChild(clone);
    return { key: cell.dataset.sortableColumnKey ?? '', clone };
  });
  anchor.appendChild(host);
  try {
    return measurements.reduce<Record<string, number>>((widths, { key, clone }) => {
      if (!key) return widths;
      const width = Math.max(MIN_COLUMN_WIDTH, Math.ceil(clone.getBoundingClientRect().width) + 1);
      widths[key] = Math.max(widths[key] ?? 0, width);
      return widths;
    }, {});
  } finally {
    host.remove();
  }
}

function isActionColumn<T extends object>(column: ColumnType<T>, key: string): boolean {
  const dataIndex = Array.isArray(column.dataIndex) ? column.dataIndex.join('.') : String(column.dataIndex ?? '');
  const normalized = `${key}|${dataIndex}`.toLocaleLowerCase();
  const title = nodeText(column.title).toLocaleLowerCase();
  return ['action', 'actions', 'operation', 'operations', 'ops'].some((token) => normalized.split('|').includes(token))
    || /(?:操作|操作项|actions?|operations?)$/i.test(title);
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
 * 操作列宽度必须由当前清单里真正可见的控件数量决定，而不是沿用各页面历史
 * 写死的 150/180/240px。这里只读取 render 返回的 React 树，不触发点击、请求
 * 或状态变更；真正的单元格仍由 Ant Design 按原 render 正常渲染。
 */
function actionControlCount(node: unknown): number {
  if (node == null || typeof node === 'boolean') return 0;
  if (Array.isArray(node)) return node.reduce((total, child) => total + actionControlCount(child), 0);
  if (typeof node === 'object' && !isValidElement(node) && 'children' in node) {
    return actionControlCount((node as { children?: unknown }).children);
  }
  if (!isValidElement<ActionElementProps>(node)) return 0;
  const element = node as ReactElement<ActionElementProps>;
  const isControl = element.type === Button
    || element.type === 'a'
    || Boolean(element.props.onClick || element.props.href || element.props.to);
  if (isControl) return 1;
  return Children.toArray(element.props.children)
    .reduce<number>((total, child) => total + actionControlCount(child), 0);
}

function actionTitleWidth(title: unknown): number {
  const label = nodeText(title);
  if (!label) return MIN_ACTION_COLUMN_WIDTH;
  const textWidth = Array.from(label).reduce(
    (width, character) => width + (/^[\u2e80-\u9fff]$/.test(character) ? 14 : 8),
    0,
  );
  return textWidth + 28;
}

function compactActionColumnWidth<T extends object>(column: ColumnType<T>, rows: T[]): number {
  const controlCount = column.render
    ? rows.reduce((maximum, row, index) => {
        try {
          const rendered = column.render!(valueAt(row, column.dataIndex), row, index);
          return Math.max(maximum, actionControlCount(rendered));
        } catch {
          // 宽度预估不能让业务 render 的异常遮蔽 Ant Design 自己的错误路径。
          return maximum;
        }
      }, 0)
    : 0;
  const controlsWidth = controlCount > 0
    ? controlCount * ACTION_ICON_WIDTH + ACTION_CELL_PADDING
    : MIN_ACTION_COLUMN_WIDTH;
  return Math.max(
    MIN_ACTION_COLUMN_WIDTH,
    Math.min(MAX_ACTION_COLUMN_WIDTH, Math.max(actionTitleWidth(column.title), controlsWidth)),
  );
}

/**
 * 统一表格排序入口。所有业务表只要使用此组件，表头字段即可点击排序，
 * 并且不会覆盖页面已经定义的自定义 sorter。
 */
export default function SortableTable<T extends object>({ autoSort = true, columns, standardToolbar, dataSource, pagination, tableKey, requiredColumnKeys = [], freezeColumns = 2, ...props }: SortableTableProps<T>) {
  const user = useAuthStore((state) => state.user);
  const setUser = useAuthStore((state) => state.setUser);
  const tableAnchorRef = useRef<HTMLDivElement>(null);
  const [appScrollContainer, setAppScrollContainer] = useState<HTMLElement | null>(null);
  const [measuredAutoWidths, setMeasuredAutoWidths] = useState<Record<string, number>>({});
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
  const rows = useMemo(() => (dataSource ?? []) as T[], [dataSource]);
  const leaves = useMemo(() => leafColumns(columns ?? []), [columns]);
  const knownKeys = useMemo(() => leaves.map((item) => item.key), [leaves]);
  const actionKeys = useMemo(
    () => new Set(leaves.filter(({ column, key }) => isActionColumn(column, key)).map(({ key }) => key)),
    [leaves],
  );
  const defaultFrozenKeys = useMemo(
    () => leaves
      .filter(({ column, key }) => !isActionColumn(column, key) && column.fixed !== 'right')
      .slice(0, Math.max(0, freezeColumns))
      .map(({ key }) => key),
    [freezeColumns, leaves],
  );
  const legacyTableKey = tableKey ?? routeTableKey(window.location.pathname);
  const resolvedTableKey = tableKey ?? `${legacyTableKey.slice(0, 54)}.${tableSchemaKey(knownKeys)}`;
  const protectedKeys = useMemo(
    () => new Set(requiredColumnKeys.concat(defaultFrozenKeys, leaves.filter(({ column }) => column.fixed === 'left' || column.fixed === 'right' || column.key === 'action' || column.key === 'actions').map(({ key }) => key))),
    [defaultFrozenKeys, leaves, requiredColumnKeys],
  );
  const automaticWidths = useMemo(() => Object.fromEntries(leaves.map(({ column, key }) => [
    key,
    isActionColumn(column, key)
      ? compactActionColumnWidth(column, rows)
      : (measuredAutoWidths[key] ?? estimatedContentColumnWidth(column, rows)),
  ])), [leaves, measuredAutoWidths, rows]);
  const legacyDefaultWidths = useMemo(() => Object.fromEntries(leaves.map(({ column, key }) => [
    key,
    isActionColumn(column, key) ? compactActionColumnWidth(column, rows) : defaultColumnWidth(column),
  ])), [leaves, rows]);
  const defaultConfig = useMemo<ViewConfig>(() => ({
    visible: knownKeys,
    widths: automaticWidths,
    manual_widths: [],
  }), [automaticWidths, knownKeys]);
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
    // 旧版会把所有默认宽度一并保存，无法区分“自动值”和用户拖拽值。迁移时
    // 只把偏离旧页面默认值的非操作列视为手工宽度，其余列立即进入内容自适应。
    const manualWidths = saved?.manual_widths != null
      ? saved.manual_widths.filter((key) => knownKeys.includes(key) && !actionKeys.has(key))
      : leaves
        .filter(({ key }) => (
          !actionKeys.has(key)
          && saved?.widths[key] != null
          && Math.abs(saved.widths[key] - (legacyDefaultWidths[key] ?? 0)) > 1
        ))
        .map(({ key }) => key);
    const savedManualWidths = Object.fromEntries(manualWidths.flatMap((key) => (
      saved?.widths[key] == null ? [] : [[key, saved.widths[key]]]
    )));
    setViewConfig({
      visible: Array.from(new Set([...visible, ...Array.from(protectedKeys).filter((key) => knownKeys.includes(key))])),
      widths: { ...defaultConfig.widths, ...savedManualWidths },
      manual_widths: manualWidths,
    });
  }, [actionKeys, defaultConfig, knownKeys, leaves, legacyDefaultWidths, legacyTableKey, protectedKeys, resolvedTableKey, user?.preferences?.table_views]);

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

  const manualWidthKeys = useMemo(() => new Set(viewConfig.manual_widths ?? []), [viewConfig.manual_widths]);
  const displayWidths = useMemo(() => {
    const visibleLeaves = leaves.filter(({ key }) => viewConfig.visible.includes(key) || protectedKeys.has(key));
    return Object.fromEntries(visibleLeaves.map(({ column, key }) => [
      key,
      isActionColumn(column, key)
        ? compactActionColumnWidth(column, rows)
        : (manualWidthKeys.has(key)
          ? (viewConfig.widths[key] ?? automaticWidths[key] ?? MIN_COLUMN_WIDTH)
          : (automaticWidths[key] ?? MIN_COLUMN_WIDTH)),
    ]));
  }, [automaticWidths, leaves, manualWidthKeys, protectedKeys, rows, viewConfig.visible, viewConfig.widths]);
  const resolvedScroll = useMemo<TableProps<T>['scroll']>(() => {
    const measuredWidth = Object.values(displayWidths).reduce((total, width) => total + width, 0)
      + (props.rowSelection ? 48 : 0);
    // 页面历史 scroll.x 只是静态估值，会重新制造空白。统一以当前可见列的
    // 实际宽度总和为唯一横向宽度；超出视口时交给原生横向滚动条访问。
    return { ...(props.scroll ?? {}), x: Math.max(1, measuredWidth) };
  }, [displayWidths, props.rowSelection, props.scroll]);

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
        const manuallySized = manualWidthKeys.has(key);
        const fixed = source.fixed ?? (defaultFrozenKeys.includes(key) ? 'left' : undefined);
        // 操作列按当前结果集中实际可见的最大控件数计算，并统一限制在
        // 64-176px；这样既能容纳状态相关操作，也不会被历史声明或偏好撑宽。
        const width = actionColumn
          ? compactActionColumnWidth(source, rows)
          : (displayWidths[key] ?? automaticWidths[key] ?? MIN_COLUMN_WIDTH);
        const render = source.render && actionColumn
          ? ((value: unknown, record: T, renderIndex: number) => iconifyActionRender(source.render!(value, record, renderIndex))) as ColumnType<T>['render']
          : source.render;
        result.push({
          ...source,
          fixed,
          render,
          width,
          // 自动列宽已容纳当前完整内容，不再保留页面历史的省略号；用户明确
          // 拖窄某列后才恢复该列原有的 ellipsis 语义。
          ellipsis: manuallySized ? source.ellipsis : false,
          className: [
            typeof source.className === 'string' ? source.className : '',
            actionColumn ? 'sortable-table__action-cell' : '',
            !actionColumn && !manuallySized ? 'sortable-table__auto-width-cell' : '',
            fixed === 'left' ? 'sortable-table__fixed-left-cell' : '',
            fixed === 'right' ? 'sortable-table__fixed-right-cell' : '',
          ]
            .filter(Boolean)
            .join(' '),
          onCell: (record, rowIndex) => ({
            ...(source.onCell?.(record, rowIndex) ?? {}),
            'data-sortable-column-key': key,
          }),
          onHeaderCell: (headerColumn) => ({
            ...(source.onHeaderCell?.(headerColumn) ?? {}),
            width,
            'data-sortable-column-key': key,
            ...(actionColumn ? {} : {
              onResize: (nextWidth: number) => {
                const next = {
                  ...viewConfigRef.current,
                  widths: { ...viewConfigRef.current.widths, [key]: nextWidth },
                  manual_widths: Array.from(new Set([...(viewConfigRef.current.manual_widths ?? []), key])),
                };
                viewConfigRef.current = next;
                setViewConfig(next);
              },
              onResizeEnd: () => void persistViewConfig(viewConfigRef.current),
              onResizeStep: (delta: number) => {
                const nextWidth = Math.max(MIN_COLUMN_WIDTH, Math.min(MAX_COLUMN_WIDTH, width + delta));
                void persistViewConfig({
                  ...viewConfigRef.current,
                  widths: { ...viewConfigRef.current.widths, [key]: nextWidth },
                  manual_widths: Array.from(new Set([...(viewConfigRef.current.manual_widths ?? []), key])),
                });
              },
            }),
          }),
        } as ColumnType<T>);
      });
      return result;
    };
    return transform(columns ?? []);
  }, [automaticWidths, columns, defaultFrozenKeys, displayWidths, manualWidthKeys, protectedKeys, rows, viewConfig]);
  // augmentColumns 会克隆列定义；保持引用稳定，避免筛选、选择或分页等无关
  // 重渲染重复执行整表 DOM 自然宽度测量。
  const tableColumnsWithView = useMemo(
    () => autoSort && configuredColumns ? augmentColumns(configuredColumns) : configuredColumns,
    [autoSort, configuredColumns],
  );
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
  useLayoutEffect(() => {
    const anchor = tableAnchorRef.current;
    if (!anchor) return;
    const nextWidths = measureRenderedColumnWidths(anchor, actionKeys);
    setMeasuredAutoWidths((current) => sameWidths(current, nextWidths) ? current : nextWidths);
  }, [actionKeys, filteredRows, rows, tableColumnsWithView, viewConfig.visible]);
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
            className={[props.className, 'sortable-table--unified'].filter(Boolean).join(' ')}
            columns={tableColumnsWithView}
            dataSource={standardToolbar ? filteredRows : dataSource}
            pagination={tablePagination}
            scroll={resolvedScroll}
            rowSelection={props.rowSelection ? { ...props.rowSelection, fixed: props.rowSelection.fixed ?? true } : undefined}
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
