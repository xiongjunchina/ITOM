export type WbsDisplayLimit = 50 | 100 | 200 | 'all';

interface WbsHierarchyRow {
  id: string;
  parent_task_id: string | null;
}

export interface WbsPage<T> {
  rows: T[];
  page: number;
  pageCount: number;
  targetCount: number;
}

/** 按当前数组中的同级顺序生成页面实际使用的深度优先 WBS 顺序。 */
function flattenWbsRows<T extends WbsHierarchyRow>(rows: readonly T[]): T[] {
  const byId = new Map(rows.map((row) => [row.id, row]));
  const children = new Map<string | null, T[]>();
  rows.forEach((row) => {
    const parentId = row.parent_task_id && byId.has(row.parent_task_id) ? row.parent_task_id : null;
    const siblings = children.get(parentId) ?? [];
    siblings.push(row);
    children.set(parentId, siblings);
  });

  const result: T[] = [];
  const visited = new Set<string>();
  const walk = (parentId: string | null) => {
    for (const row of children.get(parentId) ?? []) {
      if (visited.has(row.id)) continue;
      visited.add(row.id);
      result.push(row);
      walk(row.id);
    }
  };
  walk(null);
  // 防御历史脏数据中的循环：不丢行，仍保留接口原顺序作为安全兜底。
  rows.forEach((row) => {
    if (!visited.has(row.id)) result.push(row);
  });
  return result;
}

/**
 * 按接口返回的既有 WBS 顺序截取任务，并补齐每个已选子任务的祖先。
 *
 * 祖先可能位于截取边界之外，因此返回行数允许略多于指定上限；最终过滤
 * 仍沿用原数组顺序，交给现有树构建逻辑恢复层级，不改变同级排序。
 */
export function selectHierarchySafeWbsRows<T extends WbsHierarchyRow>(
  rows: readonly T[],
  limit: WbsDisplayLimit,
): T[] {
  return selectHierarchySafeWbsPage(rows, limit, 1).rows;
}

/**
 * 按 WBS 深度优先顺序分页，并为当前页目标行补齐祖先。
 *
 * 页码只按目标行计算，补齐的祖先不占用分页名额。因此 75 行、每页 50
 * 时，第 2 页始终以第 51–75 行为目标，再额外显示恢复树结构所需的祖先。
 */
export function selectHierarchySafeWbsPage<T extends WbsHierarchyRow>(
  rows: readonly T[],
  limit: WbsDisplayLimit,
  requestedPage: number,
): WbsPage<T> {
  const orderedRows = flattenWbsRows(rows);
  if (limit === 'all') {
    return { rows: orderedRows, page: 1, pageCount: 1, targetCount: orderedRows.length };
  }

  const pageCount = Math.max(1, Math.ceil(orderedRows.length / limit));
  const page = Math.min(Math.max(Math.trunc(requestedPage) || 1, 1), pageCount);
  const start = (page - 1) * limit;
  const targets = orderedRows.slice(start, start + limit);
  if (orderedRows.length <= limit) {
    return { rows: orderedRows, page, pageCount, targetCount: targets.length };
  }

  const byId = new Map(orderedRows.map((row) => [row.id, row]));
  const includedIds = new Set(targets.map((row) => row.id));

  for (const row of targets) {
    const visited = new Set<string>();
    let parentId = row.parent_task_id;
    while (parentId && !visited.has(parentId)) {
      visited.add(parentId);
      const parent = byId.get(parentId);
      if (!parent) break;
      includedIds.add(parent.id);
      parentId = parent.parent_task_id;
    }
  }

  return {
    rows: orderedRows.filter((row) => includedIds.has(row.id)),
    page,
    pageCount,
    targetCount: targets.length,
  };
}
