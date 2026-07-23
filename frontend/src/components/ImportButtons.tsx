import { useState } from 'react';
import { Button, Modal, Space, Typography, Upload, message } from 'antd';
import type { UploadProps } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import Table from './SortableTable';
import {
  CheckCircleOutlined,
  DownloadOutlined,
  ExclamationCircleOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import { api } from '../api/client';
import { useT } from '../i18n';
import type { ImportFailedRow, ImportResult } from '../api/types';

type TFn = ReturnType<typeof useT>;

interface ImportButtonsProps {
  /** 模板下载地址（相对 /api，如 /itsm-import/ci/template） */
  templateUrl: string;
  /** 导入上传地址（相对 /api，如 /itsm-import/ci） */
  importUrl: string;
  /** 结果弹窗关闭后回调（刷新列表） */
  onDone: () => void;
  buttonText?: string;
}

const CREATED_KEYS = ['catalogs', 'items', 'wbs', 'milestones'] as const;

/** 成功数文案：created 为数字或分项对象（键经 comp.import.created.* 映射） */
function createdText(created: ImportResult['created'], t: TFn): string {
  if (typeof created === 'number') return t('comp.import.successN', { n: created });
  const parts = Object.entries(created as Record<string, number>).map(([k, v]) =>
    t('comp.import.itemN', {
      label: (CREATED_KEYS as readonly string[]).includes(k) ? t('comp.import.created.' + k) : k,
      n: v,
    }),
  );
  return t('comp.import.successPrefix') + parts.join(t('comp.listSep'));
}

/**
 * Excel 批量导入按钮组：「下载模板」+「批量导入」。
 * 部分成功语义：有效行已入库，失败行带行号原因在结果弹窗中列出，修正后可重新导入。
 */
export default function ImportButtons({
  templateUrl,
  importUrl,
  onDone,
  buttonText,
}: ImportButtonsProps) {
  const t = useT();
  const [downloading, setDownloading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);

  const handleDownload = async () => {
    setDownloading(true);
    try {
      await api.download(templateUrl);
    } catch {
      // 已统一提示
    } finally {
      setDownloading(false);
    }
  };

  const beforeUpload: UploadProps['beforeUpload'] = (file) => {
    if (!file.name.toLowerCase().endsWith('.xlsx')) {
      message.error(t('comp.import.xlsxOnly'));
      return Upload.LIST_IGNORE;
    }
    return true;
  };

  const customRequest: NonNullable<UploadProps['customRequest']> = ({ file, onSuccess, onError }) => {
    setImporting(true);
    api
      .upload<ImportResult>(importUrl, file as File)
      .then((res) => {
        setResult(res);
        onSuccess?.(res);
      })
      .catch((e) => {
        // 已统一提示（403 / 文件格式等整体失败）
        onError?.(e as Error);
      })
      .finally(() => setImporting(false));
  };

  const closeResult = () => {
    setResult(null);
    onDone();
  };

  const failed = result?.failed ?? [];
  const allOk = failed.length === 0;
  const showSheet = failed.some((f) => !!f.sheet);
  const failedColumns: ColumnsType<ImportFailedRow> = [
    ...(showSheet
      ? ([{ title: t('comp.import.col.sheet'), dataIndex: 'sheet', width: 100, render: (v: string) => v || '-' }] as ColumnsType<ImportFailedRow>)
      : []),
    { title: t('comp.import.col.row'), dataIndex: 'row', width: 80, align: 'right' },
    { title: t('comp.import.col.error'), dataIndex: 'error' },
  ];

  return (
    <>
      <Space>
        <Button icon={<DownloadOutlined />} loading={downloading} onClick={() => void handleDownload()}>
          {t('comp.import.downloadTemplate')}
        </Button>
        <Upload
          accept=".xlsx"
          showUploadList={false}
          beforeUpload={beforeUpload}
          customRequest={customRequest}
          disabled={importing}
        >
          <Button icon={<UploadOutlined />} loading={importing}>
            {buttonText ?? t('comp.import.batchImport')}
          </Button>
        </Upload>
      </Space>

      <Modal
        title={
          allOk ? (
            <Space>
              <CheckCircleOutlined style={{ color: '#52c41a' }} />
              {t('comp.import.successTitle')}
            </Space>
          ) : (
            <Space>
              <ExclamationCircleOutlined style={{ color: '#faad14' }} />
              {t('comp.import.partialTitle')}
            </Space>
          )
        }
        open={!!result}
        onCancel={closeResult}
        footer={
          <Button type="primary" onClick={closeResult}>
            {t('comp.import.gotIt')}
          </Button>
        }
        width={620}
      >
        {result && (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Typography.Text strong>{createdText(result.created, t)}</Typography.Text>
            {!allOk && (
              <>
                <Typography.Text type="warning">
                  {t('comp.import.failedHint', { n: failed.length })}
                </Typography.Text>
                <Table<ImportFailedRow>
                  size="small"
                  rowKey={(r, i) => `${r.sheet ?? ''}-${r.row}-${i ?? 0}`}
                  columns={failedColumns}
                  dataSource={failed}
                  pagination={
                    failed.length > 10
                      ? { pageSize: 10, size: 'small', showTotal: (total) => t('comp.totalN', { n: total }) }
                      : false
                  }
                />
              </>
            )}
          </Space>
        )}
      </Modal>
    </>
  );
}
