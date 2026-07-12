import { DICT, type Dict } from './dict';
import { useLangStore, type Lang } from './store';

export type { Lang };
export { useLangStore };

/** 纯函数翻译：t(lang, key, params?)；缺 key 回退中文，再回退 key。 */
export function translate(lang: Lang, key: string, params?: Record<string, string | number>): string {
  const table: Dict = DICT[lang] ?? DICT.zh;
  let s = table[key] ?? DICT.zh[key] ?? key;
  if (params) {
    for (const k of Object.keys(params)) s = s.replace(new RegExp(`\\{${k}\\}`, 'g'), String(params[k]));
  }
  return s;
}

/** 组件内翻译 hook：随语言 store 响应式更新。 */
export function useT() {
  const lang = useLangStore((s) => s.lang);
  return (key: string, params?: Record<string, string | number>) => translate(lang, key, params);
}

/** 当前语言（非响应式读取，用于事件回调）。 */
export function currentLang(): Lang {
  return useLangStore.getState().lang;
}
