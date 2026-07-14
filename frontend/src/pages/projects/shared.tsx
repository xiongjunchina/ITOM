import { Badge, Tag } from 'antd';
import { api } from '../../api/client';
import type { ProjectHealth, ProjectStatus, RequirementRow, RiskGrade } from '../../api/types';
import { HEALTH_META, PROJECT_STATUS, ROUTE_PROJECT } from '../../api/types';
import { currentLang, useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';

/** M16 可关联需求候选：实现中 + 实现路径=转项目管理 + 尚未挂接项目（前端过滤，供新建项目/章程导入下拉） */
export async function fetchLinkableRequirements(): Promise<RequirementRow[]> {
  const res = await api.getList<RequirementRow>('/requirements', {
    status: 'implementing',
    page: 1,
    page_size: 200,
  });
  return res.items.filter((r) => r.route === ROUTE_PROJECT && !r.project_id && !r.is_example);
}

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
  const et = useEnums();
  const meta = HEALTH_META[health as ProjectHealth] ?? HEALTH_META.green;
  const key = HEALTH_META[health as ProjectHealth] ? (health as ProjectHealth) : 'green';
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
      {et.health(key)}
    </span>
  );
}

/** 风险等级：高×高→红「高危」；含高→橙「中高」；其余灰「一般」 */
export function riskLevel(probability: string, impact: string): { key: 'high' | 'mid' | 'normal'; color: string } {
  if (probability === '高' && impact === '高') return { key: 'high', color: 'red' };
  if (probability === '高' || impact === '高') return { key: 'mid', color: 'orange' };
  return { key: 'normal', color: 'default' };
}

export function RiskLevelTag({ probability, impact }: { probability: RiskGrade; impact: RiskGrade }) {
  const t = useT();
  const lv = riskLevel(probability, impact);
  return <Tag color={lv.color}>{t(`proj.risk.level.${lv.key}`)}</Tag>;
}

/** 万元数字展示：null → '-'（zh 追加「万」单位；en 由 label 承载单位，仅显示数值） */
export function fmt10k(v: number | null | undefined): string {
  if (v == null) return '-';
  return currentLang() === 'en' ? `${v}` : `${v} 万`;
}

/** 百分比展示：null → '-' */
export function fmtPct(v: number | null | undefined): string {
  return v == null ? '-' : `${v}%`;
}
