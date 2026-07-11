/** 考核期工具：半年期编码 "YYYY-H1" / "YYYY-H2"（与后端 current_period 同规则） */

/** 当前考核期，如 2026-H2 */
export function currentPeriod(d: Date = new Date()): string {
  return `${d.getFullYear()}-H${d.getMonth() + 1 <= 6 ? 1 : 2}`;
}

/** 近 years 年（含当年）的全部半年期选项，升序，如 [2025-H1, 2025-H2, 2026-H1, 2026-H2] */
export function recentPeriods(years = 2): string[] {
  const year = new Date().getFullYear();
  const list: string[] = [];
  for (let y = year - years + 1; y <= year; y += 1) {
    list.push(`${y}-H1`, `${y}-H2`);
  }
  return list;
}
