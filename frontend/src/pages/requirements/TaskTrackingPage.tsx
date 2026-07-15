import { Card } from 'antd';
import { useT } from '../../i18n';
import ActiveTaskList from './ActiveTaskList';

/** 任务跟踪（M17 二级菜单独立页）：跨需求聚合的开发任务清单 */
export default function TaskTrackingPage() {
  const t = useT();
  return (
    <Card title={t('req.tab.tasks')}>
      <ActiveTaskList />
    </Card>
  );
}
