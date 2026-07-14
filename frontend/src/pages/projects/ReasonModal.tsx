import { useState } from 'react';
import { Input, Modal, Typography, message } from 'antd';
import { useT } from '../../i18n';

/**
 * 暂停/关闭理由弹窗（M14.1，列表与详情页共用）：
 * 理由必填（≥2 字），提交后写入最新动态与审计日志（后端强制校验 REASON_REQUIRED）。
 */
export default function ReasonModal({
  open,
  opLabel,
  projectName,
  onClose,
  onSubmit,
}: {
  open: boolean;
  /** 操作名（暂停/关闭），用于标题与占位符 */
  opLabel: string;
  projectName: string;
  onClose: () => void;
  onSubmit: (reason: string) => Promise<void>;
}) {
  const t = useT();
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (reason.trim().length < 2) {
      message.warning(t('proj.op.reasonRequired'));
      return;
    }
    setSaving(true);
    try {
      await onSubmit(reason.trim());
      setReason('');
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={t('proj.op.reasonTitle', { op: opLabel, name: projectName })}
      open={open}
      onCancel={() => {
        setReason('');
        onClose();
      }}
      onOk={() => void submit()}
      confirmLoading={saving}
      okText={t('common.confirm')}
      cancelText={t('common.cancel')}
    >
      <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
        {t('proj.op.reasonHint')}
      </Typography.Paragraph>
      <Input.TextArea
        rows={3}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder={t('proj.op.reasonPlaceholder', { op: opLabel })}
        maxLength={200}
        showCount
      />
    </Modal>
  );
}
