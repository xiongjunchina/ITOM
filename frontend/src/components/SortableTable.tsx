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

function sanitizeViewConfig(value: unknown): ViewConfig | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const raw = value as { visible?: unknown; widths?: unknown };
  if (!Array.isArray(raw.visible) || !raw.visible.every((key) => typeof key === 'string')) return null;
  if (!raw.widths || typeof raw.widths !== 'object' || Array.isArray(raw.widths)) return null;
  const widths = Object.fromEntries(
    Object.entries(raw.widths as Record<string, unknown>)
      .filter(([key, width]) => typeof key === 'string' && Number.isFinite(width) && typeof width === 'number')
      .map(([key, width]) => [key, Math.max(80, Math.min(800, Math.trunc(width as number)))]),
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

function ResizableHeaderCell(props: Record<string, unknown>) {
  const { children, onResize, onResizeEnd, width, ...rest } = props as {
    children?: ReactNode;
    onResize?: (width: number) => void;
    onResizeEnd?: (width: number) => void;
    width?: number;
    [key: string]: unknown;
  };
  if (!onResize || !width) return <th {...rest}>{children}</th>;
  const startResize = (event: ReactMouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startWidth = width;
    let lastWidth = startWidth;
    const move = (moveEvent: globalThis.MouseEvent) => {
      lastWidth = Math.max(80, Math.min(800, startWidth + moveEvent.clientX - startX));
      onResize(lastWidth);
    };
    const stop = () => {
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', stop);
      onResizeEnd?.(lastWidth);
    };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', stop);
  };
  return (
    <th {...rest} style={{ ...(rest.style as CSSProperties | undefined), position: 'relative' }}>
      {children}
      <span
        role="separator"
        aria-label="resize column"
        onMouseDown={startResize}
        style={{ position: 'absolute', top: 0, right: -3, width: 8, height: '100%', cursor: 'col-resize', zIndex: 2 }}
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
  const resolvedTableKey = tableKey ?? routeTableKey(window.location.pathname);
  const leaves = useMemo(() => leafColumns(columns ?? []), [columns]);
  const knownKeys = useMemo(() => leaves.map((item) => item.key), [leaves]);
  const protectedKeys = useMemo(
    () => new Set(requiredColumnKeys.concat(leaves.filter(({ column }) => column.fixed === 'left' || column.fixed === 'right' || column.key === 'action' || column.key === 'actions').map(({ key }) => key))),
    [leaves, requiredColumnKeys],
  );
  const defaultConfig = useMemo<ViewConfig>(() => ({
    visible: knownKeys,
    widths: Object.fromEntries(leaves.filter(({ column }) => typeof column.width === 'number').map(({ column, key }) => [key, column.width as number])),
  }), [knownKeys, leaves]);
  const [viewConfig, setViewConfig] = useState<ViewConfig>(defaultConfig);
  const viewConfigRef = useRef(viewConfig);
  useEffect(() => {
    viewConfigRef.current = viewConfig;
  }, [viewConfig]);

  useEffect(() => {
    const saved = sanitizeViewConfig(user?.preferences?.table_views?.[resolvedTableKey]);
    const savedVisible = saved?.visible.filter((key) => knownKeys.includes(key)) ?? [];
    const visible = saved ? savedVisible : knownKeys;
    setViewConfig({
      visible: Array.from(new Set([...visible, ...Array.from(protectedKeys).filter((key) => knownKeys.includes(key))])),
      widths: { ...defaultConfig.widths, ...(saved?.widths ?? {}) },
    });
  }, [defaultConfig, knownKeys, protectedKeys, resolvedTableKey, user?.preferences?.table_views]);

  const persistViewConfig = async (next: ViewConfig) => {
    viewConfigRef.current = next;
    setViewConfig(next);
    if (!user) return;
    const tableViews = { ...sanitizeTableViews(user.preferences?.table_views), [resolvedTableKey]: next };
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
      const width = viewConfig.widths[key] ?? source.width;
      result.push({
        ...source,
        ...(width ? { width } : {}),
        onHeaderCell: () => ({
          width,
          onResize: (nextWidth: number) => {
            const next = { ...viewConfigRef.current, widths: { ...viewConfigRef.current.widths, [key]: nextWidth } };
            viewConfigRef.current = next;
            setViewConfig(next);
          },
          onResizeEnd: () => void persistViewConfig(viewConfigRef.current),
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
          components={{ ...(props.components ?? {}), header: { ...(props.components?.header ?? {}), cell: ResizableHeaderCell } }}
        />
      </Space>
    </>
  );
}
