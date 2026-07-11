import type { Department } from '../api/types';

/**
 * 部门平铺列表 → 树（同级按 sort、code 排序）。
 * excludeId：排除该节点及其整棵子树（编辑部门时选上级用，防止成环）。
 * 父节点缺失（或被排除）之外的孤儿节点提升为顶级。
 */
export function buildDeptTree<T>(
  depts: Department[],
  make: (dept: Department, children: T[]) => T,
  excludeId?: string,
): T[] {
  const ids = new Set(depts.map((d) => d.id));
  const byParent = new Map<string | null, Department[]>();
  depts.forEach((d) => {
    if (excludeId && d.id === excludeId) return;
    const pid = d.parent_id && ids.has(d.parent_id) ? d.parent_id : null;
    byParent.set(pid, [...(byParent.get(pid) ?? []), d]);
  });
  const walk = (pid: string | null): T[] =>
    (byParent.get(pid) ?? [])
      .slice()
      .sort((a, b) => (a.sort ?? 0) - (b.sort ?? 0) || a.code.localeCompare(b.code))
      .map((d) => make(d, walk(d.id)));
  return walk(null);
}

export interface DeptTreeNode {
  value: string;
  title: string;
  children?: DeptTreeNode[];
}

/** 部门列表 → antd TreeSelect 的 treeData */
export function buildDeptTreeSelectData(
  depts: Department[],
  excludeId?: string,
): DeptTreeNode[] {
  return buildDeptTree<DeptTreeNode>(
    depts,
    (d, children) => ({
      value: d.id,
      title: d.active ? d.name : `${d.name}（已停用）`,
      ...(children.length > 0 ? { children } : {}),
    }),
    excludeId,
  );
}
