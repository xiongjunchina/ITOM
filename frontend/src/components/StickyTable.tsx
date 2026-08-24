import {
  Children,
  cloneElement,
  isValidElement,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import type {
  CSSProperties,
  HTMLAttributes,
  Key,
  PointerEvent as ReactPointerEvent,
  ReactElement,
  ReactNode,
} from 'react';
import type { ColumnType, ColumnsType, TableProps } from 'antd/es/table';
import SortableTable from './SortableTable';

const MIN_COLUMN_WIDTH = 64;
const MIN_ROW_HEIGHT = 32;
const MAX_ROW_HEIGHT = 360;

type StickyTableProps<T extends object> = TableProps<T> & {
  /** 冻结左侧列数量，WBS 使用前三列。 */
  freezeColumns?: number;
  /** 是否允许拖拽表头右侧调整列宽。 */
  resizable?: boolean;
  /** 是否允许拖拽行底部调整行高。 */
  rowResizable?: boolean;
  /** 可选的本地布局存储键，保存列宽和行高。 */
  storageKey?: string;
};

type ResizeHeaderCellProps = HTMLAttributes<HTMLTableCellElement> & {
  onResizeStart?: (event: ReactPointerEvent<HTMLSpanElement>) => void;
  onResizeStep?: (delta: number) => void;
};

type ResizeBodyRowProps = HTMLAttributes<HTMLTableRowElement> & {
  'data-row-key'?: Key;
  children?: ReactNode;
};

type ResizeCellProps = {
  children?: ReactNode;
  className?: string;
  style?: CSSProperties;
};

function ResizeHeaderCell({ onResizeStart, onResizeStep, children, ...props }: ResizeHeaderCellProps) {
  return (
    <th {...props} className={`${props.className ?? ''} sticky-table__header-cell`}>
      {children}
      {onResizeStart && (
        <span
          className="sticky-table__column-resize-handle"
          role="separator"
          aria-label="调整列宽"
          aria-orientation="vertical"
          tabIndex={0}
          onPointerDown={onResizeStart}
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
      )}
    </th>
  );
}

function getColumnKey<T extends object>(column: ColumnType<T>, index: number): string {
  if (column.key != null) return String(column.key);
  if (column.dataIndex != null) {
    return Array.isArray(column.dataIndex) ? column.dataIndex.join('.') : String(column.dataIndex);
  }
  return `column-${index}`;
}

function readLayout(storageKey: string | undefined): {
  columnWidths: Record<string, number>;
  rowHeights: Record<string, number>;
} {
  if (!storageKey || typeof window === 'undefined') return { columnWidths: {}, rowHeights: {} };
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) return { columnWidths: {}, rowHeights: {} };
    const parsed = JSON.parse(raw) as { columnWidths?: Record<string, number>; rowHeights?: Record<string, number> };
    return {
      columnWidths: parsed.columnWidths ?? {},
      rowHeights: parsed.rowHeights ?? {},
    };
  } catch {
    return { columnWidths: {}, rowHeights: {} };
  }
}

/**
 * Excel 式宽表：
 * - 表头与唯一底部原生横向滚动条相对 app-content 悬浮；
 * - freezeColumns 冻结左侧列；
 * - 表头分隔线和行底部分隔线支持鼠标/键盘调整；
 * - 可选 storageKey 保存个人布局。
 */
export default function StickyTable<T extends object>({
  className = '',
  freezeColumns = 0,
  resizable = false,
  rowResizable = false,
  storageKey,
  ...props
}: StickyTableProps<T>) {
  const tableWrapRef = useRef<HTMLDivElement>(null);
  const resizeCleanupRef = useRef<(() => void) | null>(null);
  const initialLayout = useMemo(() => readLayout(storageKey), [storageKey]);
  const [stickyContainer, setStickyContainer] = useState<HTMLElement | null>(null);
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>(initialLayout.columnWidths);
  const [rowHeights, setRowHeights] = useState<Record<string, number>>(initialLayout.rowHeights);

  useEffect(() => {
    const layout = readLayout(storageKey);
    setColumnWidths(layout.columnWidths);
    setRowHeights(layout.rowHeights);
  }, [storageKey]);

  useEffect(() => {
    if (!storageKey || typeof window === 'undefined') return;
    try {
      window.localStorage.setItem(storageKey, JSON.stringify({ columnWidths, rowHeights }));
    } catch {
      // 隐私模式或存储配额不足时，布局仍在当前页面会话中生效。
    }
  }, [columnWidths, rowHeights, storageKey]);

  useLayoutEffect(() => {
    const wrapper = tableWrapRef.current;
    if (!wrapper) return;
    // MainLayout 的 app-content 是固定高度后的唯一纵向滚动容器；其他场景退回 window。
    setStickyContainer(wrapper.closest<HTMLElement>('.app-content'));
  }, []);

  const startColumnResize = useCallback((key: string, event: ReactPointerEvent<HTMLSpanElement>) => {
    event.preventDefault();
    event.stopPropagation();
    resizeCleanupRef.current?.();
    const header = event.currentTarget.closest('th');
    const initialWidth = header?.getBoundingClientRect().width ?? MIN_COLUMN_WIDTH;
    const startX = event.clientX;
    const update = (nextWidth: number) => {
      setColumnWidths((current) => ({ ...current, [key]: Math.max(MIN_COLUMN_WIDTH, Math.round(nextWidth)) }));
    };
    const onMove = (moveEvent: PointerEvent) => update(initialWidth + moveEvent.clientX - startX);
    const onUp = () => {
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerup', onUp);
      resizeCleanupRef.current = null;
    };
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp, { once: true });
    resizeCleanupRef.current = onUp;
  }, []);

  const resizeColumnBy = useCallback((key: string, delta: number) => {
    setColumnWidths((current) => ({
      ...current,
      [key]: Math.max(MIN_COLUMN_WIDTH, Math.round((current[key] ?? MIN_COLUMN_WIDTH) + delta)),
    }));
  }, []);

  const startRowResize = useCallback((key: string, event: ReactPointerEvent<HTMLSpanElement>) => {
    event.preventDefault();
    event.stopPropagation();
    resizeCleanupRef.current?.();
    const cell = event.currentTarget.closest('td');
    const row = event.currentTarget.closest('tr');
    const initialHeight = row?.getBoundingClientRect().height ?? cell?.getBoundingClientRect().height ?? MIN_ROW_HEIGHT;
    const startY = event.clientY;
    const update = (nextHeight: number) => {
      setRowHeights((current) => ({
        ...current,
        [key]: Math.min(MAX_ROW_HEIGHT, Math.max(MIN_ROW_HEIGHT, Math.round(nextHeight))),
      }));
    };
    const onMove = (moveEvent: PointerEvent) => update(initialHeight + moveEvent.clientY - startY);
    const onUp = () => {
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerup', onUp);
      resizeCleanupRef.current = null;
    };
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp, { once: true });
    resizeCleanupRef.current = onUp;
  }, []);

  const resizeRowBy = useCallback((key: string, delta: number) => {
    setRowHeights((current) => ({
      ...current,
      [key]: Math.min(MAX_ROW_HEIGHT, Math.max(MIN_ROW_HEIGHT, Math.round((current[key] ?? MIN_ROW_HEIGHT) + delta))),
    }));
  }, []);

  useEffect(() => () => resizeCleanupRef.current?.(), []);

  const tableColumns = useMemo<ColumnsType<T> | undefined>(() => {
    if (!props.columns) return undefined;
    return props.columns.map((column, index) => {
      if ('children' in column) return column;
      const source = column as ColumnType<T>;
      const key = getColumnKey(source, index);
      const originalHeaderCell = source.onHeaderCell;
      const next: ColumnType<T> = {
        ...source,
        ...(columnWidths[key] != null ? { width: columnWidths[key] } : {}),
        ...(freezeColumns > index ? { fixed: 'left' as const } : {}),
      };
      if (resizable) {
        next.onHeaderCell = (columnInfo) => ({
          ...(originalHeaderCell?.(columnInfo) ?? {}),
          onResizeStart: (event: ReactPointerEvent<HTMLSpanElement>) => startColumnResize(key, event),
          onResizeStep: (delta: number) => resizeColumnBy(key, delta),
        } as ResizeHeaderCellProps);
      }
      return next;
    });
  }, [columnWidths, freezeColumns, props.columns, resizable, resizeColumnBy, startColumnResize]);

  const bodyRow = useMemo(() => {
    if (!rowResizable) return undefined;
    return function ResizableBodyRow(rowProps: ResizeBodyRowProps) {
      const key = String(rowProps['data-row-key'] ?? '');
      const height = rowHeights[key];
      const cells = Children.toArray(rowProps.children);
      // Ant Design 在启用 rowSelection 后会把选择框单元格插入第一列。
      // 行高拖拽手柄必须挂在第一个业务单元格，不能覆盖选择框原有 children。
      const resizeCellIndex = cells.findIndex((cell) => (
        isValidElement<ResizeCellProps>(cell)
        && !String(cell.props.className ?? '').includes('ant-table-selection-column')
      ));
      const decoratedCells = key && resizeCellIndex >= 0
        ? cells.map((cell, index) => {
            if (index !== resizeCellIndex || !isValidElement<ResizeCellProps>(cell)) return cell;
            return cloneElement(cell as ReactElement<ResizeCellProps>, {
              className: `${cell.props.className ?? ''} sticky-table__row-resize-cell`,
              style: { ...cell.props.style, position: 'relative' },
              children: (
                <>
                  {cell.props.children}
                  <span
                    className="sticky-table__row-resize-handle"
                    role="separator"
                    aria-label="调整行高"
                    aria-orientation="horizontal"
                    tabIndex={0}
                    onPointerDown={(event) => startRowResize(key, event)}
                    onKeyDown={(event) => {
                      if (event.key === 'ArrowUp') {
                        event.preventDefault();
                        resizeRowBy(key, -8);
                      } else if (event.key === 'ArrowDown') {
                        event.preventDefault();
                        resizeRowBy(key, 8);
                      }
                    }}
                  />
                </>
              ),
            });
          })
        : cells;
      return (
        <tr {...rowProps} style={{ ...rowProps.style, ...(height ? { height } : {}) }}>
          {decoratedCells}
        </tr>
      );
    };
  }, [resizeRowBy, rowHeights, rowResizable, startRowResize]);

  const components = useMemo(() => ({
    header: resizable ? { cell: ResizeHeaderCell } : undefined,
    body: bodyRow ? { row: bodyRow } : undefined,
  }), [bodyRow, resizable]);

  const sticky = useMemo(
    () => ({
      offsetHeader: 0,
      getContainer: () => stickyContainer ?? window,
    }),
    [stickyContainer],
  );

  return (
    <div className={`sticky-table ${freezeColumns > 0 ? 'sticky-table--freeze-columns' : ''} ${className}`}>
      <div
        ref={tableWrapRef}
        className="sticky-table__body"
      >
        <SortableTable<T>
          {...props}
          columns={tableColumns}
          components={components}
          sticky={sticky}
        />
      </div>
    </div>
  );
}
