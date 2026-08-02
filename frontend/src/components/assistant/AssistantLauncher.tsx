import { useState } from 'react';
import { Button } from 'antd';
import { RobotOutlined } from '@ant-design/icons';
import { useT } from '../../i18n';
import AssistantDrawer from './AssistantDrawer';
import './assistant.css';

export default function AssistantLauncher() {
  const t = useT();
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button
        className="assistant-launcher"
        icon={<RobotOutlined />}
        aria-label={t('assistant.launcher')}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
      >
        <span className="assistant-launcher__label">{t('assistant.launcher')}</span>
      </Button>
      <AssistantDrawer open={open} onClose={() => setOpen(false)} />
    </>
  );
}
