import { create } from 'zustand';
import { api } from '../api/client';

export interface UiBrandingConfig {
  brand: Record<string, string>;
  login: Record<string, string | boolean>;
  appearance: { primary_color: string; default_theme: string; default_density: string; sidebar_theme: string; show_system_name_in_header: boolean };
  roles: Record<string, string>;
  announcement: { enabled: boolean; type: 'info' | 'warning' | 'maintenance'; text_zh: string; text_en: string; starts_at: string; ends_at: string; dismissible: boolean; show_on_login: boolean };
  environment: { label: string; show_marker: boolean };
}
export interface BrandingVersion { id: string | null; version: number; status: string; config: UiBrandingConfig; updated_at?: string }

interface BrandingState { current: BrandingVersion | null; loaded: boolean; load: () => Promise<void>; setCurrent: (value: BrandingVersion) => void }
export const useBrandingStore = create<BrandingState>((set) => ({
  current: null, loaded: false,
  load: async () => { try { set({ current: await api.get<BrandingVersion>('/public/ui-branding'), loaded: true }); } catch { set({ loaded: true }); } },
  setCurrent: (current) => set({ current }),
}));
export function localized(config: UiBrandingConfig | undefined, section: 'brand' | 'login' | 'announcement', field: string, lang: 'zh' | 'en', fallback = ''): string {
  const values = config?.[section] as Record<string, unknown> | undefined;
  return String(values?.[`${field}_${lang}`] || fallback);
}
