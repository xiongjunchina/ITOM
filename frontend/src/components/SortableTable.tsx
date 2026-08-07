import { Button, Card, Checkbox, Divider, Dropdown, Space, Table, Tooltip } from 'antd';
import { useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent as ReactMouseEvent, type ReactNode } from 'react';
import TableStandardToolbar, { type TableStandardOptions } from './TableStandardToolbar';
import type { ColumnType, ColumnsType, TableProps } from 'antd/es/table';
import { SettingOutlined } from '@ant-design/icons';
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
const MIN_COLUMN_WIDTH = 80;
const MAX_COLUMN_WIDTH = 800;

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
  if (!onResize || !width) return <th {...rest}>{children}</th>;
  const startResize = (event: ReactMouseEvent<HTMLSpanElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startWidth = width;
    let lastWidth = startWidth;
    const previousCursor = document.body.style.cursor;
    document.body.style.cursor = 'col-resize';
    const move = (moveEvent: MouseEvent) => {
      lastWidth = Math.max(MIN_COLUMN_WIDTH, Math.min(MAX_COLUMN_WIDTH, startWidth + moveEvent.clientX - startX));
      onResize(lastWidth);
    };
    const stop = () => {
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', stop);
      document.body.style.cursor = previousCursor;
      onResizeEnd?.(lastWidth);
    };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', stop, { once: true });
  };
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
        onMouseDown={startResize}
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

/**
 * 统一表格排序入口。所有业务表只要使用此组件，表头字段即可点击排序，
 * 并且不会覆盖页面已经定义的自定义 sorter。
 */
export default function SortableTable<T extends object>({ autoSort = true, columns, standardToolbar, dataSource, pagination, tableKey, requiredColumnKeys = [], ...props }: SortableTableProps<T>) {
  const user = useAuthStore((state) => state.user);
  const setUser = useAuthStore((state) => state.setUser);
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
    widths: Object.fromEntries(leaves.map(({ column, key }) => [key, defaultColumnWidth(column)])),
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
      const width = viewConfig.widths[key] ?? defaultColumnWidth(source);
      result.push({
        ...source,
        width,
        onHeaderCell: (headerColumn) => ({
          ...(source.onHeaderCell?.(headerColumn) ?? {}),
          width,
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
        <Table<T>
          {...props}
          columns={tableColumnsWithView}
          dataSource={standardToolbar ? filteredRows : dataSource}
          pagination={tablePagination}
          scroll={{ x: 'max-content', ...(props.scroll ?? {}) }}
          // 明确固定布局，列宽状态变化才会同步应用到 colgroup，而不是被单元格
          // 内容重新撑回原宽度。
          tableLayout={props.tableLayout ?? 'fixed'}
          components={{ ...(props.components ?? {}), header: { ...(props.components?.header ?? {}), cell: headerCell } }}
        />
      </Space>
    </>
  );
}
