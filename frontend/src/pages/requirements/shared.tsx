import { Badge, Tag } from 'antd';
import dayjs from 'dayjs';
import type { Moscow, RequirementStatus } from '../../api/types';
import { MOSCOW_META, REQ_STATUS } from '../../api/types';
import { useEnums } from '../../i18n/enums';

/** 需求状态 Badge（未知状态回退灰点 + 后端中文名） */
export function ReqStatusBadge({ status, name }: { status: string; name?: string | null }) {
  const meta = REQ_STATUS[status as RequirementStatus];
  const text = name || meta?.label || status;
  if (!meta) return <Badge status="default" text={text} />;
  return meta.color ? (
    <Badge color={meta.color} text={text} />
  ) : (
    <Badge status={meta.badge} text={text} />
  );
}

/** MoSCoW Tag：M红 / S橙 / C蓝 / W灰；空值显示占位符 */
export function MoscowTag({ value, empty = '-' }: { value?: string | null; empty?: string | null }) {
  const et = useEnums();
  if (!value) return empty == null ? null : <span style={{ color: 'rgba(0,0,0,0.25)' }}>{empty}</span>;
  const meta = MOSCOW_META[value as Moscow];
  if (!meta) return <Tag>{value}</Tag>;
  return <Tag color={meta.color}>{et.moscow(value)}</Tag>;
}

/** 日期时间展示：ISO → YYYY-MM-DD HH:mm；空 → undefined（配合 Steps description） */
export function fmtDt(v?: string | null): string | undefined {
  return v ? dayjs(v).format('YYYY-MM-DD HH:mm') : undefined;
}
