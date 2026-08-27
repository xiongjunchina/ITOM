export const DEVELOPMENT_TASK_TABS = ['requirement', 'bug', 'project'] as const;

export type DevelopmentTaskTab = (typeof DEVELOPMENT_TASK_TABS)[number];

/** Keep the URL query string and the rendered development-task panel in sync. */
export function resolveDevelopmentTaskTab(value: string | null): DevelopmentTaskTab {
  return DEVELOPMENT_TASK_TABS.includes(value as DevelopmentTaskTab)
    ? value as DevelopmentTaskTab
    : 'requirement';
}
