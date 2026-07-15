import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { AuthUser, Role } from '../api/types';
import { useLangStore } from '../i18n/store';

interface AuthState {
  token: string | null;
  user: AuthUser | null;
  setAuth: (token: string, user: AuthUser) => void;
  setUser: (user: AuthUser) => void;
  logout: () => void;
}

/** 登录/刷新时应用用户的显示语言（后端 payload.language 或 preferences.language）。 */
function applyUserLanguage(user: AuthUser) {
  const lang = user.language ?? user.preferences?.language;
  if (lang === 'zh' || lang === 'en') useLangStore.getState().setLang(lang);
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      setAuth: (token, user) => {
        applyUserLanguage(user);
        set({ token, user });
      },
      setUser: (user) => {
        applyUserLanguage(user);
        set({ user });
      },
      logout: () => set({ token: null, user: null }),
    }),
    { name: 'new-aom-auth' },
  ),
);

/** 用户是否拥有 roles 中任一角色；roles 为空表示所有登录用户可见 */
export function hasAnyRole(user: AuthUser | null, roles?: Role[]): boolean {
  if (!roles || roles.length === 0) return true;
  if (!user) return false;
  return user.roles.some((r) => roles.includes(r));
}

/**
 * 功能权限判断：permissions["*"]（admin 隐式全权）或 permissions[module] 含该动作。
 * 仅当 user.permissions 存在时有意义；存量会话缺失 permissions 时调用方应回退角色逻辑。
 */
export function hasPermission(user: AuthUser | null, module: string, action = 'view'): boolean {
  const perms = user?.permissions;
  if (!perms) return false;
  if (perms['*']) return true;
  return (perms[module] ?? []).includes(action);
}

/**
 * 流程任务可操作判断（M18/M25，与后端 can_act_on_task 同规则）：
 * admin、任务处理人本人；未指派任务由步骤默认角色持有者认领操作。
 */
export function canHandleTask(
  user: AuthUser | null,
  step: { assignee?: string | null; default_role?: string | null },
): boolean {
  if (!user) return false;
  if (user.permissions?.['*']) return true;
  if (step.assignee) return !!user.person_id && step.assignee === user.person_id;
  return !!step.default_role && (user.roles as string[]).includes(step.default_role);
}
