import { useState } from 'react';
import { Button, Modal, Space, Table, Typography, Upload, message } from 'antd';
import type { UploadProps } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  CheckCircleOutlined,
  DownloadOutlined,
  ExclamationCircleOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import { api } from '../api/client';
import type { ImportFailedRow, ImportResult } from '../api/types';

interface ImportButtonsProps {
  /** 模板下载地址（相对 /api，如 /itsm-import/ci/template） */
  templateUrl: string;
  /** 导入上传地址（相对 /api，如 /itsm-import/ci） */
  importUrl: string;
  /** 结果弹窗关闭后回调（刷新列表） */
  onDone: () => void;
  buttonText?: string;
}

const CREATED_LABELS: Record<string, string> = {
  catalogs: '目录',
  items: '服务项',
  wbs: 'WBS 任务',
  milestones: '里程碑',
};

/** 成功数文案：created 为数字或分项对象（键经 CREATED_LABELS 映射） */
function createdText(created: ImportResult['created']): string {
  if (typeof created === 'number') return `成功导入 ${created} 条`;
  const parts = Object.entries(created as Record<string, number>).map(
    ([k, v]) => `${CREATED_LABELS[k] ?? k} ${v} 条`,
  );
  return `成功导入：${parts.join('、')}`;
}

/**
 * Excel 批量导入按钮组：「下载模板」+「批量导入」。
 * 部分成功语义：有效行已入库，失败行带行号原因在结果弹窗中列出，修正后可重新导入。
 */
export default function ImportButtons({
  templateUrl,
  importUrl,
  onDone,
  buttonText = '批量导入',
}: ImportButtonsProps) {
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
      message.error('仅支持 .xlsx 文件（请使用下载的模板填写）');
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
      ? ([{ title: '工作表', dataIndex: 'sheet', width: 100, render: (v: string) => v || '-' }] as ColumnsType<ImportFailedRow>)
      : []),
    { title: '行号', dataIndex: 'row', width: 80, align: 'right' },
    { title: '失败原因', dataIndex: 'error' },
  ];

  return (
    <>
      <Space>
        <Button icon={<DownloadOutlined />} loading={downloading} onClick={() => void handleDownload()}>
          下载模板
        </Button>
        <Upload
          accept=".xlsx"
          showUploadList={false}
          beforeUpload={beforeUpload}
          customRequest={customRequest}
          disabled={importing}
        >
          <Button icon={<UploadOutlined />} loading={importing}>
            {buttonText}
          </Button>
        </Upload>
      </Space>

      <Modal
        title={
          allOk ? (
            <Space>
              <CheckCircleOutlined style={{ color: '#52c41a' }} />
              导入成功
            </Space>
          ) : (
            <Space>
              <ExclamationCircleOutlined style={{ color: '#faad14' }} />
              导入完成（部分行失败）
            </Space>
          )
        }
        open={!!result}
        onCancel={closeResult}
        footer={
          <Button type="primary" onClick={closeResult}>
            知道了
          </Button>
        }
        width={620}
      >
        {result && (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Typography.Text strong>{createdText(result.created)}</Typography.Text>
            {!allOk && (
              <>
                <Typography.Text type="warning">
                  {failed.length} 行未导入：失败行修正后可重新导入（已导入的行会自动跳过）
                </Typography.Text>
                <Table<ImportFailedRow>
                  size="small"
                  rowKey={(r, i) => `${r.sheet ?? ''}-${r.row}-${i ?? 0}`}
                  columns={failedColumns}
                  dataSource={failed}
                  pagination={
                    failed.length > 10
                      ? { pageSize: 10, size: 'small', showTotal: (t) => `共 ${t} 条` }
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
