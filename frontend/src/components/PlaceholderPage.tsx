import { Card, Empty } from 'antd';

interface Props {
  title: string;
}

/** M2-M6 里程碑占位页 */
export default function PlaceholderPage({ title }: Props) {
  return (
    <Card title={title}>
      <Empty
        style={{ padding: '64px 0' }}
        description="本模块将在 M2-M6 里程碑交付"
      />
    </Card>
  );
}
