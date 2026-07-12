/**
 * 考核期工具（与后端 current_period 同规则，2026-07-12 定稿季度制）：
 * Q1/Q2/Q3 单季考核；Q4 不单独考核，10-12 月进入全年考核期 "YYYY-All"（统计范围=全年）。
 */

/** 当前考核期，如 2026-Q3；10-12 月返回 2026-All */
export function currentPeriod(d: Date = new Date()): string {
  const quarter = Math.floor(d.getMonth() / 3) + 1;
  return quarter === 4 ? `${d.getFullYear()}-All` : `${d.getFullYear()}-Q${quarter}`;
}

/** 近 years 年（含当年）的全部考核期选项，升序，如 [2025-Q1, 2025-Q2, 2025-Q3, 2025-All, 2026-Q1, …] */
export function recentPeriods(years = 2): string[] {
  const year = new Date().getFullYear();
  const list: string[] = [];
  for (let y = year - years + 1; y <= year; y += 1) {
    list.push(`${y}-Q1`, `${y}-Q2`, `${y}-Q3`, `${y}-All`);
  }
  return list;
}

/** 考核期显示名：2026-All → 「2026 全年」，其余原样 */
export function periodLabel(p: string): string {
  return p.endsWith('-All') ? `${p.split('-')[0]} 全年` : p;
}
