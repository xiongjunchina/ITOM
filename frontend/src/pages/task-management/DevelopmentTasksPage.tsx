import { Card, Tabs } from 'antd';
import { useSearchParams } from 'react-router-dom';
import { useT } from '../../i18n';
import ActiveTaskList from '../requirements/ActiveTaskList';
import BugListPage from './BugListPage';

/** 开发任务：需求开发沿用原有需求任务清单，Bug 修复使用独立字段和流程。 */
export default function DevelopmentTasksPage() {
  const t = useT();
  const [searchParams, setSearchParams] = useSearchParams();
  const active = searchParams.get('tab') === 'bug' ? 'bug' : 'requirement';
  return (
    <Card title={t('menu./task-management/development')}>
      <Tabs
        activeKey={active}
        onChange={(key) => setSearchParams({ tab: key })}
        items={[
          { key: 'requirement', label: t('task.tab.requirement'), children: <ActiveTaskList /> },
          { key: 'bug', label: t('task.tab.bug'), children: <BugListPage /> },
        ]}
      />
    </Card>
  );
}
