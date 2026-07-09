import { Navigate, createBrowserRouter } from 'react-router-dom';
import MainLayout from './components/MainLayout';
import PlaceholderPage from './components/PlaceholderPage';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Positions from './pages/team/Positions';
import Users from './pages/admin/Users';
import Members from './pages/admin/Members';
import MasterData from './pages/admin/MasterData';
import AuditLogs from './pages/admin/AuditLogs';
import Tickets from './pages/itsm/Tickets';
import TicketDetail from './pages/itsm/TicketDetail';
import CatalogPage from './pages/itsm/CatalogPage';
import SlaBoard from './pages/itsm/SlaBoard';

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
      { path: 'itsm/cmdb', element: <PlaceholderPage title="CMDB" /> },
      { path: 'itsm/problems', element: <PlaceholderPage title="问题" /> },
      { path: 'itsm/vendors', element: <PlaceholderPage title="供应商" /> },
      { path: 'itsm/contracts', element: <PlaceholderPage title="合同" /> },
      { path: 'itsm/knowledge', element: <PlaceholderPage title="知识库" /> },

      { path: 'projects', element: <PlaceholderPage title="项目管理" /> },
      { path: 'requirements', element: <PlaceholderPage title="需求管理" /> },

      // 流程中心（M2+ 交付）
      { path: 'process/definitions', element: <PlaceholderPage title="流程定义" /> },
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
      { path: 'admin/members', element: <Members /> },
      { path: 'admin/master-data', element: <MasterData /> },
      { path: 'admin/audit-logs', element: <AuditLogs /> },

      { path: '*', element: <Navigate to="/dashboard" replace /> },
    ],
  },
]);
