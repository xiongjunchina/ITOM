import { useEffect, useState } from 'react';
import { Button, Modal, Space, Typography } from 'antd';
import { api } from '../api/client';
import { useT } from '../i18n';

export type ItDocumentType = 'service_request' | 'incident' | 'problem' | 'change' | 'requirement' | 'project';

export interface ItDocumentGuideItem {
  type: ItDocumentType;
  label: string;
  suitable: string;
  positive_example: string;
  not_suitable: string;
  redirect: string;
  target_path: string | null;
  can_create: boolean;
}

export interface ItDocumentGuideResponse {
  version: string;
  staff_intake: { enabled: boolean; available_types: ItDocumentType[] };
  documents: ItDocumentGuideItem[];
}

/** 页面标题下的紧凑单据说明；详情默认仅占一行，完整案例按需查看。 */
export default function DocumentTypeHint({ documentType }: { documentType: ItDocumentType }) {
  const [item, setItem] = useState<ItDocumentGuideItem | null>(null);
  const [open, setOpen] = useState(false);
  const t = useT();

  useEffect(() => {
    let active = true;
    api
      .get<ItDocumentGuideResponse>('/it-document-guide')
      .then((guide) => {
        if (active) setItem(guide.documents.find((candidate) => candidate.type === documentType) ?? null);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [documentType]);

  if (!item) return null;

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0, marginBottom: 16 }}>
        <Typography.Text type="secondary" ellipsis={{ tooltip: item.suitable }} style={{ minWidth: 0 }}>
          {item.suitable}
        </Typography.Text>
        <Button type="link" size="small" style={{ padding: 0, flex: 'none' }} onClick={() => setOpen(true)}>
          {t('intake.viewExamples')}
        </Button>
      </div>
      <Modal title={`${item.label} · ${t('intake.guideTitle')}`} open={open} footer={null} onCancel={() => setOpen(false)}>
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <div><Typography.Text strong>{t('intake.suitable')}</Typography.Text><div>{item.suitable}</div></div>
          <div><Typography.Text strong>{t('intake.example')}</Typography.Text><div>{item.positive_example}</div></div>
          <div><Typography.Text strong>{t('intake.notSuitable')}</Typography.Text><div>{item.not_suitable}</div></div>
          <div><Typography.Text strong>{t('intake.redirect')}</Typography.Text><div>{item.redirect}</div></div>
        </Space>
      </Modal>
    </>
  );
}
