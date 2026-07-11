import { Badge, Tag } from 'antd';
import type { ProjectHealth, ProjectStatus, RiskGrade } from '../../api/types';
import { HEALTH_META, PROJECT_STATUS } from '../../api/types';

/** 项目状态 Badge（未知状态回退灰点 + 后端中文名） */
export function StatusBadge({ status, name }: { status: string; name?: string | null }) {
  const meta = PROJECT_STATUS[status as ProjectStatus];
  const text = name || meta?.label || status;
  if (!meta) return <Badge status="default" text={text} />;
  return meta.color ? (
    <Badge color={meta.color} text={text} />
  ) : (
    <Badge status={meta.badge} text={text} />
  );
}

/** 健康度圆点 + 文字 */
export function HealthDot({ health }: { health: ProjectHealth | string }) {
  const meta = HEALTH_META[health as ProjectHealth] ?? HEALTH_META.green;
  return (
    <span style={{ whiteSpace: 'nowrap' }}>
      <span
        style={{
          display: 'inline-block',
          width: 8,
          height: 8,
          borderRadius: '50%',
          background: meta.color,
          marginRight: 6,
          verticalAlign: 'middle',
        }}
      />
      {meta.label}
    </span>
  );
}

/** 风险等级：高×高→红「高危」；含高→橙「中高」；其余灰「一般」 */
export function riskLevel(probability: string, impact: string): { label: string; color: string } {
  if (probability === '高' && impact === '高') return { label: '高危', color: 'red' };
  if (probability === '高' || impact === '高') return { label: '中高', color: 'orange' };
  return { label: '一般', color: 'default' };
}

export function RiskLevelTag({ probability, impact }: { probability: RiskGrade; impact: RiskGrade }) {
  const lv = riskLevel(probability, impact);
  return <Tag color={lv.color}>{lv.label}</Tag>;
}

/** 万元数字展示：null → '-' */
export function fmt10k(v: number | null | undefined): string {
  return v == null ? '-' : `${v} 万`;
}

/** 百分比展示：null → '-' */
export function fmtPct(v: number | null | undefined): string {
  return v == null ? '-' : `${v}%`;
}
