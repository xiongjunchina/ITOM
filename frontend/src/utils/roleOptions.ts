import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type { RoleDef, UserGroup } from '../api/types';

export interface RoleOption {
  value: string;
  label: string;
}

/**
 * 加载「角色 + 用户组」选项（default_role / cc_roles 共用词表：角色 code 或 "group:组码"），
 * 并提供 code → 中文名 的映射函数。/api/admin/roles 与 /api/admin/groups 全员可读。
 */
export function useRoleOptions() {
  const [roleOptions, setRoleOptions] = useState<RoleOption[]>([]);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([
      api.getList<RoleDef>('/admin/roles').catch(() => ({ items: [] as RoleDef[], total: 0 })),
      api.getList<UserGroup>('/admin/groups').catch(() => ({ items: [] as UserGroup[], total: 0 })),
    ]).then(([roles, groups]) => {
      if (cancelled) return;
      setRoleOptions([
        ...roles.items.map((r) => ({ value: r.code, label: r.name })),
        ...groups.items.map((g) => ({ value: `group:${g.code}`, label: `组：${g.name}` })),
      ]);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  /** 把角色 code / "group:组码" 转中文名；未匹配返回原值；空值返回「未指派」 */
  const roleLabel = useMemo(() => {
    const map = new Map(roleOptions.map((o) => [o.value, o.label]));
    return (v?: string | null) => (v ? map.get(v) ?? v : '未指派');
  }, [roleOptions]);

  return { roleOptions, roleLabel };
}
