/**
 * 六维评分维度元数据（M10）。
 * key 与后端评分字段一致（d1_strategy..d6_speed）；short 与 scoring-config 的 weights/rubric 短键一致（d1..d6）。
 * 维度名走 i18n（req.dim.*，zh/en 成对）；reverse=true 表示反向维度（分越高越差，如风险）。
 */
export interface DimensionMeta {
  /** 后端评分字段名 */
  key: 'd1_strategy' | 'd2_value' | 'd3_tech' | 'd4_org' | 'd5_risk' | 'd6_speed';
  /** 权重/档位配置短键 */
  short: 'd1' | 'd2' | 'd3' | 'd4' | 'd5' | 'd6';
  /** 展示编号 */
  code: string;
  /** 维度名 i18n key */
  nameKey: string;
  /** 反向维度（分越高越差） */
  reverse?: boolean;
}

export const DIMENSIONS: DimensionMeta[] = [
  { key: 'd1_strategy', short: 'd1', code: 'D1', nameKey: 'req.dim.d1_strategy' },
  { key: 'd2_value', short: 'd2', code: 'D2', nameKey: 'req.dim.d2_value' },
  { key: 'd3_tech', short: 'd3', code: 'D3', nameKey: 'req.dim.d3_tech' },
  { key: 'd4_org', short: 'd4', code: 'D4', nameKey: 'req.dim.d4_org' },
  { key: 'd5_risk', short: 'd5', code: 'D5', nameKey: 'req.dim.d5_risk', reverse: true },
  { key: 'd6_speed', short: 'd6', code: 'D6', nameKey: 'req.dim.d6_speed' },
];

export type DimScores = Partial<Record<DimensionMeta['key'], number>>;

/**
 * 本地实时预览：按 config.weights/thresholds 计算加权总分与四象限。
 * total = Σ weight[short] * (reverse ? 6-score : score)；
 * 象限：total≥thr.total 且 (d1+d2)/2≥thr.strategic→战略下注；total≥thr.total→速赢项目；
 *       (d1+d2)/2≥thr.viable→低优先级；否则重新评估。
 * 六维未全部填写时返回 null。
 */
export function computeScore(
  scores: DimScores,
  weights: Record<string, number>,
  thresholds: { total: number; strategic: number; viable: number },
): { total: number; quadrant: string } | null {
  if (DIMENSIONS.some((d) => scores[d.key] == null)) return null;
  let total = 0;
  for (const d of DIMENSIONS) {
    const raw = scores[d.key] as number;
    const eff = d.reverse ? 6 - raw : raw;
    total += (weights[d.short] ?? 0) * eff;
  }
  total = Math.round(total * 100) / 100;
  const strat = ((scores.d1_strategy as number) + (scores.d2_value as number)) / 2;
  let quadrant: string;
  if (total >= thresholds.total && strat >= thresholds.strategic) quadrant = '战略下注';
  else if (total >= thresholds.total) quadrant = '速赢项目';
  else if (strat >= thresholds.viable) quadrant = '低优先级';
  else quadrant = '重新评估';
  return { total, quadrant };
}
