import { Card, Tabs } from 'antd';
import { useSearchParams } from 'react-router-dom';
import { useT } from '../../i18n';
import ActiveTaskList from '../requirements/ActiveTaskList';
import BugListPage from './BugListPage';
import ProjectDevelopmentTasksPage from './ProjectDevelopmentTasksPage';
import { resolveDevelopmentTaskTab } from './developmentTaskTabs';

/** 开发任务：需求开发、Bug 修复和项目开发使用各自独立的清单与表单。 */
export default function DevelopmentTasksPage() {
  const t = useT();
  const [searchParams, setSearchParams] = useSearchParams();
  const active = resolveDevelopmentTaskTab(searchParams.get('tab'));
  return (
    <Card title={t('menu./task-management/development')}>
      <Tabs
        activeKey={active}
        onChange={(key) => setSearchParams({ tab: key })}
        items={[
          { key: 'requirement', label: t('task.tab.requirement'), children: <ActiveTaskList /> },
          { key: 'bug', label: t('task.tab.bug'), children: <BugListPage /> },
          { key: 'project', label: t('task.tab.project'), children: <ProjectDevelopmentTasksPage /> },
        ]}
      />
    </Card>
  );
}
