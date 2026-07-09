import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { AuthUser, Role } from '../api/types';

interface AuthState {
  token: string | null;
  user: AuthUser | null;
  setAuth: (token: string, user: AuthUser) => void;
  setUser: (user: AuthUser) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      setAuth: (token, user) => set({ token, user }),
      setUser: (user) => set({ user }),
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
