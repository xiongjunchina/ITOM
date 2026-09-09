import { useState } from 'react';
import { Button, Modal, Space, Table, Tag, Typography, Upload, message } from 'antd';
import type { UploadProps } from 'antd';
import { DownloadOutlined, UploadOutlined } from '@ant-design/icons';
import { api } from '../api/client';
import { useT } from '../i18n';
import type { ColumnsType } from 'antd/es/table';
import type {
  WbsRoundtripAction,
  WbsRoundtripCommitResult,
  WbsRoundtripPreview,
  WbsRoundtripPreviewRow,
} from '../api/types';

interface WbsRoundtripButtonsProps {
  exportUrl: string;
  previewUrl: string;
  commitUrl: string;
  onDone: () => void;
}

const ACTION_COLORS: Record<WbsRoundtripAction, string> = {
  create: 'success',
  update: 'processing',
  unchanged: 'default',
  blocked: 'error',
};

/**
 * WBS 专用回导控件。它不能复用通用 ImportButtons：通用导入采用部分成功的
 * 追加语义，而回导必须先预览并以一个事务提交更新/新增差异。
 */
export default function WbsRoundtripButtons({ exportUrl, previewUrl, commitUrl, onDone }: WbsRoundtripButtonsProps) {
  const t = useT();
  const [downloading, setDownloading] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<WbsRoundtripPreview | null>(null);

  const actionText = (action: WbsRoundtripAction) => t(`proj.wbs.roundtrip.action.${action}`);

  const download = async () => {
    setDownloading(true);
    try {
      await api.download(exportUrl);
    } finally {
      setDownloading(false);
    }
  };

  const beforeUpload: UploadProps['beforeUpload'] = (candidate) => {
    if (!candidate.name.toLowerCase().endsWith('.xlsx')) {
      message.error(t('comp.import.xlsxOnly'));
      return Upload.LIST_IGNORE;
    }
    return true;
  };

  const customRequest: NonNullable<UploadProps['customRequest']> = ({ file: candidate, onSuccess, onError }) => {
    const selected = candidate as File;
    setPreviewing(true);
    api
      .upload<WbsRoundtripPreview>(previewUrl, selected)
      .then((result) => {
        setFile(selected);
        setPreview(result);
        onSuccess?.(result);
      })
      .catch((error) => onError?.(error as Error))
      .finally(() => setPreviewing(false));
  };

  const close = () => {
    if (committing) return;
    reset();
  };

  const reset = () => {
    setPreview(null);
    setFile(null);
  };

  const commit = async () => {
    if (!file || !preview?.can_commit) return;
    setCommitting(true);
    try {
      const result = await api.upload<WbsRoundtripCommitResult>(commitUrl, file);
      message.success(t('proj.wbs.roundtrip.committed', { n: result.applied.create + result.applied.update }));
      reset();
      onDone();
    } finally {
      setCommitting(false);
    }
  };

  const rowColumns: ColumnsType<WbsRoundtripPreviewRow> = [
    { title: t('comp.import.col.row'), dataIndex: 'row', width: 72, align: 'right' as const },
    { title: t('proj.wbs.col.code'), dataIndex: 'wbs_code', width: 112 },
    { title: t('proj.wbs.col.name'), dataIndex: 'name', ellipsis: true },
    {
      title: t('proj.wbs.roundtrip.result'),
      dataIndex: 'action',
      width: 96,
      render: (action: WbsRoundtripAction) => <Tag color={ACTION_COLORS[action]}>{actionText(action)}</Tag>,
    },
  ];

  return (
    <>
      <Space wrap>
        <Button icon={<DownloadOutlined />} loading={downloading} onClick={() => void download()}>
          {t('proj.wbs.roundtrip.export')}
        </Button>
        <Upload
          accept=".xlsx"
          showUploadList={false}
          beforeUpload={beforeUpload}
          customRequest={customRequest}
          disabled={previewing || committing}
        >
          <Button icon={<UploadOutlined />} loading={previewing}>
            {t('proj.wbs.roundtrip.import')}
          </Button>
        </Upload>
      </Space>

      <Modal
        title={t('proj.wbs.roundtrip.title')}
        open={!!preview}
        onCancel={close}
        width={780}
        footer={[
          <Button key="cancel" disabled={committing} onClick={close}>{t('comp.import.gotIt')}</Button>,
          <Button key="commit" type="primary" loading={committing} disabled={!preview?.can_commit} onClick={() => void commit()}>
            {t('proj.wbs.roundtrip.confirm')}
          </Button>,
        ]}
      >
        {preview && (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Typography.Text>
              {t('proj.wbs.roundtrip.summary', { ...preview.summary })}
            </Typography.Text>
            {preview.summary.omitted > 0 && (
              <Typography.Text type="secondary">
                {t('proj.wbs.roundtrip.omitted', { n: preview.summary.omitted })}
              </Typography.Text>
            )}
            {preview.errors.length > 0 && (
              <>
                <Typography.Text type="danger">
                  {t('proj.wbs.roundtrip.blocked', { n: preview.errors.length })}
                </Typography.Text>
                <Table
                  size="small"
                  rowKey={(row) => `${row.row}-${row.error}`}
                  columns={[
                    { title: t('comp.import.col.row'), dataIndex: 'row', width: 72, align: 'right' as const },
                    { title: t('comp.import.col.error'), dataIndex: 'error' },
                  ]}
                  dataSource={preview.errors}
                  pagination={preview.errors.length > 8 ? { pageSize: 8, size: 'small' } : false}
                />
              </>
            )}
            <Table<WbsRoundtripPreviewRow>
              size="small"
              rowKey={(row) => `${row.row}-${row.task_id ?? 'new'}`}
              columns={rowColumns}
              dataSource={preview.rows}
              pagination={preview.rows.length > 8 ? { pageSize: 8, size: 'small' } : false}
            />
          </Space>
        )}
      </Modal>
    </>
  );
}
