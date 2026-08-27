interface WbsSelectableRow {
  id: string;
  parent_task_id: string | null;
  completed_locked?: boolean;
}

export type WbsDropPosition = 'before' | 'inside' | 'after';

export interface WbsDropDestination {
  parentTaskId: string | null;
  beforeTaskId: string | null;
}

function hierarchyMaps<T extends WbsSelectableRow>(rows: readonly T[]) {
  const byId = new Map(rows.map((row) => [row.id, row]));
  const children = new Map<string, T[]>();
  rows.forEach((row) => {
    if (!row.parent_task_id || !byId.has(row.parent_task_id)) return;
    const siblings = children.get(row.parent_task_id) ?? [];
    siblings.push(row);
    children.set(row.parent_task_id, siblings);
  });
  return { byId, children };
}

function orderedWbsRows<T extends WbsSelectableRow>(rows: readonly T[]): T[] {
  const { byId, children } = hierarchyMaps(rows);
  const roots = rows.filter((row) => !row.parent_task_id || !byId.has(row.parent_task_id));
  const result: T[] = [];
  const visited = new Set<string>();
  const walk = (row: T) => {
    if (visited.has(row.id)) return;
    visited.add(row.id);
    result.push(row);
    (children.get(row.id) ?? []).forEach(walk);
  };
  roots.forEach(walk);
  rows.forEach(walk);
  return result;
}

export function wbsBranchIds<T extends WbsSelectableRow>(rows: readonly T[], taskId: string): string[] {
  const { byId, children } = hierarchyMaps(rows);
  if (!byId.has(taskId)) return [];
  const result: string[] = [];
  const visited = new Set<string>();
  const stack = [taskId];
  while (stack.length) {
    const current = stack.pop()!;
    if (visited.has(current)) continue;
    visited.add(current);
    result.push(current);
    const direct = children.get(current) ?? [];
    for (let index = direct.length - 1; index >= 0; index -= 1) stack.push(direct[index].id);
  }
  return result;
}

/** 父级勾选/取消会覆盖所有可操作后代；完成锁定行始终保留为禁用。 */
export function toggleWbsBranchSelection<T extends WbsSelectableRow>(
  rows: readonly T[],
  currentIds: readonly string[],
  taskId: string,
  selected: boolean,
): string[] {
  const { byId, children } = hierarchyMaps(rows);
  const next = new Set(currentIds.filter((id) => byId.has(id) && !byId.get(id)?.completed_locked));
  for (const id of wbsBranchIds(rows, taskId)) {
    if (byId.get(id)?.completed_locked) continue;
    if (selected) next.add(id);
    else next.delete(id);
  }
  // 逐级回算父复选框：所有可操作直接子项均选中才选中父项，否则父项
  // 进入未选/半选状态。完成锁定子项不参与可操作选择集合。
  const visited = new Set<string>();
  let parentId = byId.get(taskId)?.parent_task_id ?? null;
  while (parentId && !visited.has(parentId)) {
    visited.add(parentId);
    const parent = byId.get(parentId);
    if (!parent) break;
    const selectableChildren = (children.get(parentId) ?? []).filter((child) => !child.completed_locked);
    if (!parent.completed_locked && selectableChildren.length && selectableChildren.every((child) => next.has(child.id))) {
      next.add(parentId);
    } else {
      next.delete(parentId);
    }
    parentId = parent.parent_task_id;
  }
  return rows.filter((row) => next.has(row.id)).map((row) => row.id);
}

/**
 * 拖动已选行时移动全部选中根；父子同时选中只保留最高层祖先。
 * 拖动未选中行则只移动该行（其后代随树自动移动）。
 */
export function normalizeWbsMoveRoots<T extends WbsSelectableRow>(
  rows: readonly T[],
  selectedIds: readonly string[],
  draggedId: string,
): string[] {
  const { byId } = hierarchyMaps(rows);
  const selected = new Set(selectedIds.filter((id) => byId.has(id)));
  const candidates = selected.has(draggedId) ? selected : new Set([draggedId]);
  return orderedWbsRows(rows)
    .filter((row) => candidates.has(row.id))
    .filter((row) => {
      const visited = new Set<string>();
      let parentId = row.parent_task_id;
      while (parentId && !visited.has(parentId)) {
        if (candidates.has(parentId)) return false;
        visited.add(parentId);
        parentId = byId.get(parentId)?.parent_task_id ?? null;
      }
      return true;
    })
    .map((row) => row.id);
}

export function wbsSelectionState<T extends WbsSelectableRow>(
  rows: readonly T[],
  selectedIds: readonly string[],
  taskId: string,
): { checked: boolean; indeterminate: boolean } {
  const byId = new Map(rows.map((row) => [row.id, row]));
  const selectable = wbsBranchIds(rows, taskId).filter((id) => !byId.get(id)?.completed_locked);
  if (!selectable.length) return { checked: false, indeterminate: false };
  const selected = new Set(selectedIds);
  const count = selectable.filter((id) => selected.has(id)).length;
  return { checked: count === selectable.length, indeterminate: count > 0 && count < selectable.length };
}

export function wbsDropPositionFromRatio(ratio: number): WbsDropPosition {
  if (ratio < 0.25) return 'before';
  if (ratio > 0.75) return 'after';
  return 'inside';
}

/** 将表格三段落点转换成服务端的父任务/前置锚点契约。 */
export function resolveWbsDropDestination<T extends WbsSelectableRow>(
  rows: readonly T[],
  movedTreeIds: ReadonlySet<string>,
  targetId: string,
  position: WbsDropPosition,
): WbsDropDestination | null {
  const target = rows.find((row) => row.id === targetId);
  if (!target || movedTreeIds.has(target.id)) return null;
  if (position === 'inside') return { parentTaskId: target.id, beforeTaskId: null };
  if (position === 'before') return { parentTaskId: target.parent_task_id, beforeTaskId: target.id };
  const siblings = orderedWbsRows(rows).filter(
    (row) => row.parent_task_id === target.parent_task_id && !movedTreeIds.has(row.id),
  );
  const targetIndex = siblings.findIndex((row) => row.id === target.id);
  return {
    parentTaskId: target.parent_task_id,
    beforeTaskId: targetIndex >= 0 ? siblings[targetIndex + 1]?.id ?? null : null,
  };
}
