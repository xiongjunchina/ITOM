import type { AssistantPageContext } from '../../api/types';

const GLID = /^[0-9A-HJKMNP-TV-Z]{26}$/;

interface ContextRule {
  pattern: RegExp;
  pageType: string;
  entityType?: string;
  allowSelection?: boolean;
  tabs?: readonly string[];
}

const exact = (path: string) => new RegExp(`^${path.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`);

const STATIC_PAGES: Array<readonly [path: string, pageType: string, tabs?: readonly string[]]> = [
  ['/', 'home'],
  ['/dashboard', 'dashboard'],
  ['/profile', 'profile', ['account', 'preferences', 'security', 'audit']],
  ['/user-manual', 'user_manual'],
  ['/itsm/tickets', 'service_request_list'],
  ['/itsm/incidents', 'incident_list'],
  ['/itsm/changes', 'change_list'],
  ['/itsm/catalog', 'service_catalog'],
  ['/itsm/sla', 'sla_board'],
  ['/itsm/cmdb', 'cmdb'],
  ['/itsm/problems', 'problem_list'],
  ['/itsm/vendors', 'vendor_list'],
  ['/itsm/contracts', 'contract_list'],
  ['/itsm/knowledge', 'knowledge_list'],
  ['/itsm/knowledge/new', 'knowledge_create'],
  ['/projects/list', 'project_list'],
  ['/projects/portfolios', 'portfolio_list'],
  ['/requirements/overview', 'requirement_list'],
  ['/requirements/scoring', 'requirement_scoring'],
  ['/task-management/development', 'development_tasks', ['requirement', 'bug', 'project']],
  ['/task-management/delegated', 'delegated_tasks'],
  ['/process/definitions', 'process_definitions'],
  ['/process/monitor', 'process_monitor'],
  ['/team/overview', 'team_overview'],
  ['/team/performance', 'performance'],
  ['/team/positions', 'positions'],
  ['/team/learning-growth', 'learning_growth', ['training', 'growth']],
  ['/team/ideas', 'activity_points', ['activities', 'point-rules']],
  ['/team/charter', 'team_charter'],
  ['/admin/org', 'admin_organization', ['architecture', 'domains']],
  ['/admin/identity', 'admin_identity', ['users', 'groups']],
  ['/admin/access', 'admin_access', ['roles', 'provision', 'permissions']],
  ['/admin/master-data', 'admin_master_data'],
  ['/admin/workflow-config', 'admin_workflow'],
  ['/admin/integrations', 'admin_integrations', ['feishu', 'email', 'ldap']],
  ['/admin/ui-branding', 'admin_branding'],
  ['/admin/audit-logs', 'admin_audit'],
  ['/admin/ai-assistant', 'admin_ai', ['providers', 'profiles', 'health', 'usage', 'audits']],
];

const ROUTE_RULES: ContextRule[] = [
  { pattern: /^\/itsm\/tickets\/([0-9A-HJKMNP-TV-Z]{26})$/, pageType: 'ticket_detail', entityType: 'ticket' },
  { pattern: /^\/itsm\/problems\/([0-9A-HJKMNP-TV-Z]{26})$/, pageType: 'problem_detail', entityType: 'problem' },
  { pattern: /^\/itsm\/knowledge\/([0-9A-HJKMNP-TV-Z]{26})(?:\/edit)?$/, pageType: 'knowledge_detail', entityType: 'knowledge' },
  { pattern: /^\/projects\/([0-9A-HJKMNP-TV-Z]{26})$/, pageType: 'project_detail', entityType: 'project' },
  { pattern: /^\/requirements\/([0-9A-HJKMNP-TV-Z]{26})$/, pageType: 'requirement_detail', entityType: 'requirement' },
  { pattern: /^\/team\/performance\/review\/([0-9A-HJKMNP-TV-Z]{26})$/, pageType: 'performance_review', entityType: 'person' },
  ...STATIC_PAGES.map(([path, pageType, tabs]) => ({
    pattern: exact(path),
    pageType,
    tabs,
    allowSelection: /_list$/.test(pageType),
  })),
];

export interface ExplicitAssistantContext {
  tab?: string;
  selectedIds?: string[];
}

function normalizedPath(pathname: string): string | null {
  if (
    !pathname.startsWith('/')
    || pathname.startsWith('//')
    || pathname.includes('\\')
    || pathname.includes('%')
    || pathname.includes('?')
    || pathname.includes('#')
    || pathname.length > 256
  ) return null;
  return pathname;
}

function matchRule(pathname: string): { rule: ContextRule; match: RegExpExecArray } | null {
  for (const rule of ROUTE_RULES) {
    const match = rule.pattern.exec(pathname);
    if (match) return { rule, match };
  }
  return null;
}

/** Build only route-derived and page-declared identifiers; arbitrary URL/DOM/storage data is unreachable. */
export function buildAssistantPageContext(
  pathname: string,
  explicit: ExplicitAssistantContext = {},
): AssistantPageContext {
  const path = normalizedPath(pathname);
  const matched = path ? matchRule(path) : null;
  if (!path || !matched) return { route: '/', page_type: 'home', selected_ids: [] };

  const context: AssistantPageContext = {
    route: path,
    page_type: matched.rule.pageType,
    selected_ids: [],
  };
  const entityId = matched.match[1];
  if (matched.rule.entityType && entityId && GLID.test(entityId)) {
    context.entity_type = matched.rule.entityType;
    context.entity_id = entityId;
  }
  if (explicit.tab && matched.rule.tabs?.includes(explicit.tab)) context.tab = explicit.tab;
  if (matched.rule.allowSelection && explicit.selectedIds) {
    context.selected_ids = Array.from(new Set(explicit.selectedIds.filter((id) => GLID.test(id)))).slice(0, 20);
  }
  return context;
}

const CREATE_TARGETS = new Set([
  '/itsm/tickets?create=1',
  '/itsm/incidents?create=1',
  '/itsm/problems?create=1',
  '/itsm/changes?create=1',
  '/requirements/overview?create=1',
  '/projects/list?create=1',
]);

/** Navigation from streamed/server data is limited to known internal pages and fixed native-create targets. */
export function safeAssistantNavigationPath(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > 300) return null;
  if (CREATE_TARGETS.has(value)) return value;
  const path = normalizedPath(value);
  return path && matchRule(path) ? path : null;
}

/** The request still reaches server-side redaction; this copy prevents obvious credentials from being echoed in the UI. */
export function redactAssistantInputForDisplay(value: string): string {
  return value
    .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, 'Bearer [REDACTED]')
    .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, '[REDACTED]')
    .replace(/\b(authorization|cookie)\s*:\s*[^\s,;]+/gi, '$1: [REDACTED]')
    .replace(/\b(password|passwd|secret|token|api[_-]?key|access[_-]?key)\s*[:=]\s*([^\s,;]+)/gi, '$1=[REDACTED]');
}
