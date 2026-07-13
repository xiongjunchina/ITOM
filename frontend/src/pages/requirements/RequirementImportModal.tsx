import { useEffect, useState } from 'react';
import { Alert, Button, Modal, Space, Spin, Typography, Upload, message } from 'antd';
import { FileExcelOutlined, InboxOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import { useT } from '../../i18n';
import type { RequirementImportResult } from '../../api/types';

interface RequirementImportModalProps {
  open: boolean;
  onClose: () => void;
  /** 导入成功后刷新列表 */
  onImported: () => void;
}

/**
 * 需求 Excel 批量导入（单步）：上传 .xlsx → POST /requirements/import →
 * 展示成功条数与失败行号清单；有成功条目即刷新列表。
 */
export default function RequirementImportModal({ open, onClose, onImported }: RequirementImportModalProps) {
  const t = useT();
  const [uploading, setUploading] = useState(false);
  const [fileName, setFileName] = useState('');
  const [result, setResult] = useState<RequirementImportResult | null>(null);

  useEffect(() => {
    if (!open) {
      setUploading(false);
      setFileName('');
      setResult(null);
    }
  }, [open]);

  const doImport = async (file: File) => {
    setUploading(true);
    setFileName(file.name);
    try {
      const res = await api.upload<RequirementImportResult>('/requirements/import', file);
      setResult(res);
      if (res.imported > 0) {
        message.success(t('req.importResult', { n: res.imported }));
        onImported();
      }
    } catch {
      // 已统一提示
      setFileName('');
    } finally {
      setUploading(false);
    }
  };

  return (
    <Modal
      title={t('req.importTitle')}
      open={open}
      width={560}
      onCancel={onClose}
      maskClosable={false}
      footer={
        <Button type="primary" onClick={onClose}>
          {t('req.importClose')}
        </Button>
      }
    >
      {!result ? (
        <Spin spinning={uploading} tip={t('req.importParsing')}>
          <Upload.Dragger
            accept=".xlsx"
            showUploadList={false}
            disabled={uploading}
            beforeUpload={(file) => {
              void doImport(file);
              return false;
            }}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">{t('req.importDragText')}</p>
            <p className="ant-upload-hint">{t('req.importDragHint')}</p>
          </Upload.Dragger>
        </Spin>
      ) : (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Space>
            <FileExcelOutlined style={{ color: '#52c41a' }} />
            <Typography.Text>{fileName}</Typography.Text>
            <Button
              size="small"
              onClick={() => {
                setResult(null);
                setFileName('');
              }}
            >
              {t('req.importReupload')}
            </Button>
          </Space>
          <Alert type="success" showIcon message={t('req.importResult', { n: result.imported })} />
          {result.errors.length > 0 && (
            <Alert
              type="warning"
              showIcon
              message={t('req.importErrorsTitle', { n: result.errors.length })}
              description={
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {result.errors.map((e, i) => (
                    <li key={i}>{t('req.importErrorRow', { row: e.row, error: e.error })}</li>
                  ))}
                </ul>
              }
            />
          )}
        </Space>
      )}
    </Modal>
  );
}
