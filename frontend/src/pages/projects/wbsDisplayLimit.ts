export type WbsDisplayLimit = 50 | 100 | 200 | 'all';

interface WbsHierarchyRow {
  id: string;
  parent_task_id: string | null;
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
  if (limit === 'all' || rows.length <= limit) return [...rows];

  const byId = new Map(rows.map((row) => [row.id, row]));
  const includedIds = new Set(rows.slice(0, limit).map((row) => row.id));

  for (const row of rows.slice(0, limit)) {
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

  return rows.filter((row) => includedIds.has(row.id));
}
