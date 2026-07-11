import { Navigate, createBrowserRouter } from 'react-router-dom';
import MainLayout from './components/MainLayout';
import PlaceholderPage from './components/PlaceholderPage';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Positions from './pages/team/Positions';
import Users from './pages/admin/Users';
import Roles from './pages/admin/Roles';
import Groups from './pages/admin/Groups';
import Permissions from './pages/admin/Permissions';
import ProvisionRules from './pages/admin/ProvisionRules';
import Departments from './pages/admin/Departments';
import Members from './pages/admin/Members';
import BusinessDomains from './pages/admin/BusinessDomains';
import MasterData from './pages/admin/MasterData';
import AuditLogs from './pages/admin/AuditLogs';
import WorkflowConfig from './pages/admin/WorkflowConfig';
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

export const router = createBrowserRouter([
  { path: '/login', element: <Login /> },
  {
    path: '/',
    element: <MainLayout />,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: 'dashboard', element: <Dashboard /> },

      // ITSM（M2 交付：工单/服务目录/SLA）
      { path: 'itsm/tickets', element: <Tickets /> },
      { path: 'itsm/tickets/:id', element: <TicketDetail /> },
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

      { path: 'projects', element: <PlaceholderPage title="项目管理" /> },
      { path: 'requirements', element: <PlaceholderPage title="需求管理" /> },

      // 流程中心
      { path: 'process/definitions', element: <Definitions /> },
      { path: 'process/monitor', element: <PlaceholderPage title="流程监控" /> },

      // 团队管理
      { path: 'team/overview', element: <PlaceholderPage title="团队总览" /> },
      { path: 'team/performance', element: <PlaceholderPage title="人效评分" /> },
      { path: 'team/positions', element: <Positions /> },
      { path: 'team/activities', element: <PlaceholderPage title="培训发展" /> },
      { path: 'team/ideas', element: <PlaceholderPage title="建言献策" /> },
      { path: 'team/charter', element: <PlaceholderPage title="团队文化" /> },

      // 系统管理（admin）
      { path: 'admin/users', element: <Users /> },
      { path: 'admin/roles', element: <Roles /> },
      { path: 'admin/groups', element: <Groups /> },
      { path: 'admin/permissions', element: <Permissions /> },
      { path: 'admin/provision-rules', element: <ProvisionRules /> },
      { path: 'admin/departments', element: <Departments /> },
      { path: 'admin/members', element: <Members /> },
      { path: 'admin/business-domains', element: <BusinessDomains /> },
      { path: 'admin/master-data', element: <MasterData /> },
      { path: 'admin/workflow-config', element: <WorkflowConfig /> },
      { path: 'admin/audit-logs', element: <AuditLogs /> },

      { path: '*', element: <Navigate to="/dashboard" replace /> },
    ],
  },
]);
