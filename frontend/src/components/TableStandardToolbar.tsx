import type { ReactNode } from 'react';
import { useMemo } from 'react';
import { Button, Input, Select, Space, Typography } from 'antd';
import { DownloadOutlined, FilterOutlined } from '@ant-design/icons';
import type { ColumnType, ColumnsType } from 'antd/es/table';

export interface TableStandardOptions<T extends object> {
  /** 关键字搜索占位文案。默认“搜索关键字”。 */
  searchPlaceholder?: string;
  /** 默认使用所有 dataIndex 字段；可显式限制搜索字段。 */
  searchFields?: Array<keyof T | string>;
  /** 允许页面补充业务筛选（状态、类型、负责人等）。 */
  filters?: ReactNode;
  /** 导出文件名；未提供服务端导出回调时导出当前已加载数据。 */
  exportFileName?: string;
  /** 服务端分页的真实匹配总数；未传时回退为当前本地筛选结果。 */
  total?: number;
  /** 可选的服务端导出动作。传入后不再把当前页误当作完整清单。 */
  onExport?: () => void | Promise<void>;
  /** 导出按钮文案；服务端全量导出建议显式标为“导出全部数据”。 */
  exportLabel?: string;
  /** 已有页面自带搜索/筛选时，可只复用统一导出按钮。 */
  showSearch?: boolean;
  showFilter?: boolean;
  showCount?: boolean;
}

type FieldOption<T extends object> = {
  key: string;
  label: string;
  values: Array<{ value: string; label: string }>;
  read: (row: T) => unknown;
};

function readValue<T extends object>(row: T, dataIndex: ColumnType<T>['dataIndex']): unknown {
  if (dataIndex == null) return undefined;
  const path = Array.isArray(dataIndex) ? dataIndex : [dataIndex];
  return path.reduce<unknown>((value, key) => {
    if (value == null || typeof value !== 'object') return undefined;
    return (value as Record<string | number, unknown>)[key as string | number];
  }, row);
}

function textValue(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function columnLabel<T extends object>(column: ColumnType<T>, key: string): string {
  return typeof column.title === 'string' || typeof column.title === 'number' ? String(column.title) : key;
}

function flattenColumns<T extends object>(columns: ColumnsType<T>): Array<{ key: string; label: string; read: (row: T) => unknown }> {
  return columns.flatMap((column) => {
    if ('children' in column && column.children) return flattenColumns(column.children);
    const source = column as ColumnType<T>;
    const key = source.dataIndex != null
      ? (Array.isArray(source.dataIndex) ? source.dataIndex.join('.') : String(source.dataIndex))
      : (typeof source.key === 'string' || typeof source.key === 'number' ? String(source.key) : '');
    if (!key || key === 'action' || key === 'actions') return [];
    return [{ key, label: columnLabel(source, key), read: (row: T) => readValue(row, source.dataIndex ?? key) }];
  });
}

function csvCell(value: unknown): string {
  const text = textValue(value).replace(/\r?\n/g, ' ');
  return /[",]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function downloadCsv<T extends object>(rows: T[], columns: ColumnsType<T>, fileName: string) {
  const fields = flattenColumns(columns);
  const csv = [
    fields.map((field) => csvCell(field.label)).join(','),
    ...rows.map((row) => fields.map((field) => csvCell(field.read(row))).join(',')),
  ].join('\r\n');
  const blob = new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = fileName.endsWith('.csv') ? fileName : `${fileName}.csv`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

interface TableStandardToolbarProps<T extends object> {
  options: TableStandardOptions<T>;
  columns: ColumnsType<T>;
  rows: T[];
  filteredRows: T[];
  query: string;
  onQueryChange: (value: string) => void;
  filterField: string | undefined;
  filterValue: string | undefined;
  onFilterFieldChange: (value: string | undefined) => void;
  onFilterValueChange: (value: string | undefined) => void;
}

export default function TableStandardToolbar<T extends object>({
  options,
  columns,
  rows,
  filteredRows,
  query,
  onQueryChange,
  filterField,
  filterValue,
  onFilterFieldChange,
  onFilterValueChange,
}: TableStandardToolbarProps<T>) {
  const fields = useMemo(() => {
    const wanted = options.searchFields?.map(String);
    return flattenColumns(columns)
      .filter((field) => !wanted || wanted.includes(field.key))
      .map((field) => {
        const values = Array.from(new Set(rows.map((row) => textValue(field.read(row))).filter(Boolean)))
          .slice(0, 100)
          .sort((left, right) => left.localeCompare(right, ['zh-CN', 'en'], { numeric: true }));
        return { ...field, values: values.map((value) => ({ value, label: value })) } as FieldOption<T>;
      });
  }, [columns, options.searchFields, rows]);

  const selectedField = fields.find((field) => field.key === filterField);
  return (
    <div className="table-standard-toolbar" role="search" aria-label="表格搜索与筛选">
      <Space wrap size={[8, 8]}>
        {options.showSearch !== false && <Input.Search
          allowClear
          value={query}
          placeholder={options.searchPlaceholder ?? '搜索关键字'}
          onChange={(event) => onQueryChange(event.target.value)}
          style={{ width: 240 }}
        />}
        {options.showFilter !== false && fields.length > 0 && (
          <Select
            allowClear
            value={filterField}
            placeholder="核心字段"
            prefix={<FilterOutlined />}
            style={{ width: 140 }}
            options={fields.map((field) => ({ value: field.key, label: field.label }))}
            onChange={(value) => {
              onFilterFieldChange(value);
              onFilterValueChange(undefined);
            }}
          />
        )}
        {options.showFilter !== false && selectedField && selectedField.values.length > 0 && (
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            value={filterValue}
            placeholder="选择值"
            style={{ width: 180 }}
            options={selectedField.values}
            onChange={onFilterValueChange}
          />
        )}
        {options.filters}
        {options.exportFileName && (
          <Button
            icon={<DownloadOutlined />}
            onClick={() => options.onExport ? void options.onExport() : downloadCsv(filteredRows, columns, options.exportFileName as string)}
          >
            {options.exportLabel ?? (options.onExport ? '导出全部数据' : '导出当前数据')}
          </Button>
        )}
        {options.showCount !== false && <Typography.Text type="secondary" className="table-standard-toolbar__count">
          共 {options.total ?? filteredRows.length} 条
        </Typography.Text>}
      </Space>
    </div>
  );
}
