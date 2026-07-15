import { Navigate, createBrowserRouter, useSearchParams } from 'react-router-dom';
import MainLayout from './components/MainLayout';
import Login from './pages/Login';
import OnboardingPending from './pages/OnboardingPending';
import FeishuCallback from './pages/FeishuCallback';
import Dashboard from './pages/Dashboard';
import Positions from './pages/team/Positions';
import Overview from './pages/team/Overview';
import Performance from './pages/team/Performance';
import Activities from './pages/team/Activities';
import ActivityPoints from './pages/team/ActivityPoints';
import Charter from './pages/team/Charter';
import Monitor from './pages/process/Monitor';
import OrgManagement from './pages/admin/OrgManagement';
import Identity from './pages/admin/Identity';
import Access from './pages/admin/Access';
import MasterData from './pages/admin/MasterData';
import AuditLogs from './pages/admin/AuditLogs';
import WorkflowConfig from './pages/admin/WorkflowConfig';
import FeishuIntegration from './pages/admin/FeishuIntegration';
import Definitions from './pages/process/Definitions';
import Tickets from './pages/itsm/Tickets';
import TicketDetail from './pages/itsm/TicketDetail';
import CatalogPage from './pages/itsm/CatalogPage';
import SlaBoard from './pages/itsm/SlaBoard';
import Cmdb from './pages/itsm/Cmdb';
import Problems from './pages/itsm/Problems';
import ProblemDetail from './pages/itsm/ProblemDetail';
import Vendors from './pages/itsm/Vendors';
import Contracts from './pages/itsm/Contracts';
import Knowledge from './pages/itsm/Knowledge';
import KnowledgeDetail from './pages/itsm/KnowledgeDetail';
import KnowledgeEdit from './pages/itsm/KnowledgeEdit';
import Projects from './pages/projects/Projects';
import TaskTrackingPage from './pages/requirements/TaskTrackingPage';
import RequirementScoring from './pages/admin/RequirementScoring';
import ProjectDetail from './pages/projects/ProjectDetail';
import Requirements from './pages/requirements/Requirements';
import RequirementDetail from './pages/requirements/RequirementDetail';

/** M17 旧地址兼容：/projects?tab=portfolios、/requirements?tab=tasks|scoring → 新二级菜单路径 */
function LegacyProjectsRedirect() {
  const [sp] = useSearchParams();
  return <Navigate to={sp.get('tab') === 'portfolios' ? '/projects/portfolios' : '/projects/list'} replace />;
}

function LegacyRequirementsRedirect() {
  const [sp] = useSearchParams();
  const tab = sp.get('tab');
  const to = tab === 'tasks' ? '/requirements/tasks' : tab === 'scoring' ? '/requirements/scoring' : '/requirements/overview';
  return <Navigate to={to} replace />;
}

export const router = createBrowserRouter([
  { path: '/login', element: <Login /> },
  // 飞书扫码未开通的过渡页：公开路由，与 /login 平级（不在 MainLayout 内）
  { path: '/onboarding/pending', element: <OnboardingPending /> },
  // 真实飞书 OAuth 回调页：公开路由，飞书扫码后跳回此处兑换 code
  { path: '/login/feishu-callback', element: <FeishuCallback /> },
  {
    path: '/',
    element: <MainLayout />,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: 'dashboard', element: <Dashboard /> },

      // ITSM（M2 交付；M6.1 工单按类型拆分三入口，key 隔离筛选/分页状态）
      { path: 'itsm/tickets', element: <Tickets key="service_request" fixedType="service_request" /> },
      { path: 'itsm/tickets/:id', element: <TicketDetail /> },
      { path: 'itsm/incidents', element: <Tickets key="incident" fixedType="incident" /> },
      { path: 'itsm/changes', element: <Tickets key="change" fixedType="change" /> },
      { path: 'itsm/catalog', element: <CatalogPage /> },
      { path: 'itsm/sla', element: <SlaBoard /> },
      { path: 'itsm/cmdb', element: <Cmdb /> },
      { path: 'itsm/problems', element: <Problems /> },
      { path: 'itsm/problems/:id', element: <ProblemDetail /> },
      { path: 'itsm/vendors', element: <Vendors /> },
      { path: 'itsm/contracts', element: <Contracts /> },
      { path: 'itsm/knowledge', element: <Knowledge /> },
      { path: 'itsm/knowledge/new', element: <KnowledgeEdit /> },
      { path: 'itsm/knowledge/:id', element: <KnowledgeDetail /> },
      { path: 'itsm/knowledge/:id/edit', element: <KnowledgeEdit /> },

      // 项目管理（M4 交付）
      { path: 'projects', element: <LegacyProjectsRedirect /> },
      { path: 'projects/list', element: <Projects pane="list" /> },
      { path: 'projects/portfolios', element: <Projects pane="portfolios" /> },
      { path: 'projects/:id', element: <ProjectDetail /> },

      // 需求管理（M5 交付）
      { path: 'requirements', element: <LegacyRequirementsRedirect /> },
      { path: 'requirements/overview', element: <Requirements /> },
      { path: 'requirements/tasks', element: <TaskTrackingPage /> },
      { path: 'requirements/scoring', element: <RequirementScoring /> },
      { path: 'requirements/:id', element: <RequirementDetail /> },

      // 流程中心
      { path: 'process/definitions', element: <Definitions /> },
      { path: 'process/monitor', element: <Monitor /> },

      // 团队管理（M6 交付）
      { path: 'team/overview', element: <Overview /> },
      { path: 'team/performance', element: <Performance /> },
      { path: 'team/positions', element: <Positions /> },
      { path: 'team/activities', element: <Activities /> },
      { path: 'team/ideas', element: <ActivityPoints /> },
      { path: 'team/charter', element: <Charter /> },

      // 系统管理（admin，M3.9 收敛为 6 项）
      { path: 'admin/org', element: <OrgManagement /> },
      { path: 'admin/identity', element: <Identity /> },
      { path: 'admin/access', element: <Access /> },
      { path: 'admin/master-data', element: <MasterData /> },
      { path: 'admin/workflow-config', element: <WorkflowConfig /> },
      // 需求评分规则已并入需求管理标签页（2026-07-14），保留旧地址重定向
      { path: 'admin/requirement-scoring', element: <Navigate to="/requirements/scoring" replace /> },
      { path: 'admin/feishu', element: <FeishuIntegration /> },
      { path: 'admin/audit-logs', element: <AuditLogs /> },

      // 旧路由 → 新复合页对应 Tab（M3.9 前的书签/外链兼容）
      { path: 'admin/departments', element: <Navigate to="/admin/org?tab=architecture" replace /> },
      { path: 'admin/members', element: <Navigate to="/admin/org?tab=architecture" replace /> },
      { path: 'admin/business-domains', element: <Navigate to="/admin/org?tab=domains" replace /> },
      { path: 'admin/users', element: <Navigate to="/admin/identity?tab=users" replace /> },
      { path: 'admin/groups', element: <Navigate to="/admin/identity?tab=groups" replace /> },
      { path: 'admin/roles', element: <Navigate to="/admin/access?tab=roles" replace /> },
      { path: 'admin/provision-rules', element: <Navigate to="/admin/access?tab=provision" replace /> },
      { path: 'admin/permissions', element: <Navigate to="/admin/access?tab=permissions" replace /> },

      { path: '*', element: <Navigate to="/dashboard" replace /> },
    ],
  },
]);
