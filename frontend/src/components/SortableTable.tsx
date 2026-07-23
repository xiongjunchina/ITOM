import { Table } from 'antd';
import { useMemo, useState } from 'react';
import TableStandardToolbar, { type TableStandardOptions } from './TableStandardToolbar';
import type { ColumnType, ColumnsType, TableProps } from 'antd/es/table';

type SortableTableProps<T extends object> = TableProps<T> & {
  /**
   * 默认让有 dataIndex 的业务列都可排序；操作列、纯 render 列保持不可排序。
   * 传入 sorter 的列会保留页面自己的比较逻辑。
   */
  autoSort?: boolean;
  /** 可选的统一列表工具栏：关键字、字段过滤、当前数据导出。 */
  standardToolbar?: TableStandardOptions<T>;
};

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
export default function SortableTable<T extends object>({ autoSort = true, columns, standardToolbar, dataSource, pagination, ...props }: SortableTableProps<T>) {
  const tableColumns = autoSort && columns ? augmentColumns(columns) : columns;
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
      total: filteredRows.length,
      // 筛选结果可能少于当前页，强制回到第一页，避免出现“有结果但当前页为空”。
      current: query.trim() || filterField || filterValue ? 1 : pagination.current,
    }
    : pagination;
  return (
    <>
      {standardToolbar && (
        <TableStandardToolbar
          options={standardToolbar}
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
      <Table<T> {...props} columns={tableColumns} dataSource={standardToolbar ? filteredRows : dataSource} pagination={tablePagination} />
    </>
  );
}
