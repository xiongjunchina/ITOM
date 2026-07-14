import { Badge, Tag } from 'antd';
import dayjs from 'dayjs';
import type { Moscow, RequirementStatus } from '../../api/types';
import { DECISION_COLORS, MOSCOW_META, QUADRANT_META, REQ_STATUS, ROUTE_META } from '../../api/types';
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

/** 四象限 Tag：配色 + 图标（战略下注⭐金 / 速赢⚡绿 / 低优先级📋灰 / 重新评估🔄红）；空值占位 */
export function QuadrantTag({ value, empty = '-' }: { value?: string | null; empty?: string | null }) {
  const et = useEnums();
  if (!value) return empty == null ? null : <span style={{ color: 'rgba(0,0,0,0.25)' }}>{empty}</span>;
  const meta = QUADRANT_META[value];
  const label = et.quadrant(value);
  if (!meta) return <Tag>{label}</Tag>;
  return (
    <Tag color={meta.color}>
      {meta.icon} {label}
    </Tag>
  );
}

/** 评估决议 Tag：立项绿 / 搁置橙 / 驳回红；空值占位 */
export function DecisionTag({ value, empty = '-' }: { value?: string | null; empty?: string | null }) {
  const et = useEnums();
  if (!value) return empty == null ? null : <span style={{ color: 'rgba(0,0,0,0.25)' }}>{empty}</span>;
  return <Tag color={DECISION_COLORS[value]}>{et.reqDecision(value)}</Tag>;
}

/** 实现路径 Tag（M16）：需求开发实现蓝 / 转项目管理紫；空值占位 */
export function RouteTag({ value, empty = '-' }: { value?: string | null; empty?: string | null }) {
  const et = useEnums();
  if (!value) return empty == null ? null : <span style={{ color: 'rgba(0,0,0,0.25)' }}>{empty}</span>;
  return <Tag color={ROUTE_META[value]}>{et.route(value)}</Tag>;
}

/** 日期时间展示：ISO → YYYY-MM-DD HH:mm；空 → undefined（配合 Steps description） */
export function fmtDt(v?: string | null): string | undefined {
  return v ? dayjs(v).format('YYYY-MM-DD HH:mm') : undefined;
}
