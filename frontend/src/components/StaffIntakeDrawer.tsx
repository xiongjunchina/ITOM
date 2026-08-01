import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Collapse, Drawer, Space, Switch, Typography } from 'antd';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { useT } from '../i18n';
import type { ItDocumentGuideResponse, ItDocumentType } from './DocumentTypeHint';

type Recommendation = {
  recommended_type: ItDocumentType;
  recommended_label: string;
  reason: string;
  counterexample: string;
  target_path: string | null;
  permission_notice?: string;
};

type Answers = {
  broad_impact: boolean;
  recurring_or_root_cause: boolean;
  planned_production_change: boolean;
  new_capability: boolean;
};

const EMPTY_ANSWERS: Answers = {
  broad_impact: false,
  recurring_or_root_cause: false,
  planned_production_change: false,
  new_capability: false,
};

export default function StaffIntakeDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [guide, setGuide] = useState<ItDocumentGuideResponse | null>(null);
  const [answers, setAnswers] = useState<Answers>(EMPTY_ANSWERS);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [loading, setLoading] = useState(false);
  const t = useT();
  const navigate = useNavigate();

  useEffect(() => {
    if (!open) return;
    setAnswers(EMPTY_ANSWERS);
    setRecommendation(null);
    api.get<ItDocumentGuideResponse>('/it-document-guide').then(setGuide).catch(() => undefined);
  }, [open]);

  const questions = useMemo(() => [
    ['broad_impact', t('intake.q.broadImpact')],
    ['recurring_or_root_cause', t('intake.q.recurring')],
    ['planned_production_change', t('intake.q.plannedChange')],
    ['new_capability', t('intake.q.newCapability')],
  ] as [keyof Answers, string][], [t]);

  const go = (path: string | null) => {
    if (!path) return;
    onClose();
    navigate(path);
  };

  const recommend = async () => {
    setLoading(true);
    try {
      setRecommendation(await api.post<Recommendation>('/staff-intake/recommend', answers));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Drawer title={t('intake.title')} open={open} onClose={onClose} width={560} destroyOnClose>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
          {t('intake.intro')}
        </Typography.Paragraph>
        {questions.map(([key, label]) => (
          <div key={key} style={{ display: 'flex', justifyContent: 'space-between', gap: 16 }}>
            <Typography.Text>{label}</Typography.Text>
            <Switch checked={answers[key]} checkedChildren={t('common.yes')} unCheckedChildren={t('common.no')}
              onChange={(checked) => setAnswers((current) => ({ ...current, [key]: checked }))} />
          </div>
        ))}
        <Button type="primary" loading={loading} onClick={() => void recommend()}>{t('intake.recommend')}</Button>

        {recommendation && (
          <Alert
            type="info"
            showIcon
            message={`${t('intake.recommended')}：${recommendation.recommended_label}`}
            description={
              <Space direction="vertical" size={6} style={{ width: '100%' }}>
                <span>{recommendation.reason}</span>
                <Typography.Text type="secondary">{t('intake.counterexample')}：{recommendation.counterexample}</Typography.Text>
                {recommendation.permission_notice && <Typography.Text type="warning">{recommendation.permission_notice}</Typography.Text>}
                {recommendation.target_path && <Button type="primary" onClick={() => go(recommendation.target_path)}>{t('intake.goCreate')}</Button>}
              </Space>
            }
          />
        )}

        <Collapse
          items={[{
            key: 'manual',
            label: t('intake.manualChoice'),
            children: (
              <Space wrap>
                {(guide?.documents ?? []).filter((item) => item.can_create).map((item) => (
                  <Button key={item.type} onClick={() => go(item.target_path)}>{item.label}</Button>
                ))}
              </Space>
            ),
          }, {
            key: 'guide',
            label: t('intake.guideTitle'),
            children: (
              <Space direction="vertical" size={14} style={{ width: '100%' }}>
                {(guide?.documents ?? []).map((item) => (
                  <div key={item.type}>
                    <Typography.Text strong>{item.label}</Typography.Text>
                    <div>{item.suitable}</div>
                    <Typography.Text type="secondary">{item.positive_example}</Typography.Text>
                  </div>
                ))}
              </Space>
            ),
          }]}
        />
      </Space>
    </Drawer>
  );
}
