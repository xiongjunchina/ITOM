import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type Lang = 'zh' | 'en';

interface LangState {
  lang: Lang;
  setLang: (lang: Lang) => void;
}

/**
 * 显示语言（登录前生效、登录后由 user.preferences.language 覆盖并同步后端）。
 * 独立持久化，登录页在无会话时也能切换。
 */
export const useLangStore = create<LangState>()(
  persist(
    (set) => ({
      lang: 'zh',
      setLang: (lang) => set({ lang }),
    }),
    { name: 'aom-lang' },
  ),
);
