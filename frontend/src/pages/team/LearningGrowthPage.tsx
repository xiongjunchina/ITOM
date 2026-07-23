import PermTabs from '../../components/PermTabs';
import { useT } from '../../i18n';
import Activities from './Activities';
import LearningGrowth from './LearningGrowth';

/** 学习成长复合页：培训提升与学习任务在同一页面内按标签页切换。 */
export default function LearningGrowthPage() {
  const t = useT();

  return (
    <PermTabs
      tabs={[
        {
          key: 'training',
          label: t('team.learningGrowth.tab.training'),
          modules: ['activities'],
          children: <Activities />,
        },
        {
          key: 'tasks',
          label: t('team.learningGrowth.tab.tasks'),
          modules: ['learning_growth'],
          children: <LearningGrowth />,
        },
      ]}
    />
  );
}
