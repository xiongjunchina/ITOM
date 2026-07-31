import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Card, Empty, Space, Tag, Typography } from 'antd';
import { LinkOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from '../api/client';
import type { RecordRelationRow } from '../api/types';
import { useT } from '../i18n';

type EntityType = 'ticket' | 'problem' | 'requirement' | 'project';

function recordPath(row: RecordRelationRow['counterpart']): string {
  if (row.entity_type === 'ticket') {
    const section = row.record_type === 'incident' ? 'incidents' : row.record_type === 'change' ? 'changes' : 'tickets';
    return `/itsm/${section}/${row.id}`;
  }
  if (row.entity_type === 'problem') return `/itsm/problems/${row.id}`;
  if (row.entity_type === 'requirement') return `/requirements/${row.id}`;
  return `/projects/${row.id}`;
}

/** 只读关联区：前端不根据本地数据猜测权限，由后端对关系两端做可见性过滤。 */
export default function RecordRelationsPanel({
  entityType,
  entityId,
  excludeRelationTypes = [],
  hideWhenEmpty = false,
}: {
  entityType: EntityType;
  entityId: string;
  excludeRelationTypes?: string[];
  hideWhenEmpty?: boolean;
}) {
  const t = useT();
  const [rows, setRows] = useState<RecordRelationRow[]>([]);

  useEffect(() => {
    let active = true;
    api
      .get<RecordRelationRow[]>(`/records/${entityType}/${entityId}/relations`)
      .then((data) => active && setRows(data))
      .catch(() => active && setRows([]));
    return () => {
      active = false;
    };
  }, [entityId, entityType]);

  const visibleRows = rows.filter((row) => !excludeRelationTypes.includes(row.relation_type));
  if (hideWhenEmpty && visibleRows.length === 0) return null;

  return (
    <Card title={<Space><LinkOutlined />{t('comp.relations.title')}</Space>} size="small">
      {visibleRows.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('comp.relations.empty')} />
      ) : (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          {visibleRows.map((row) => (
            <div key={row.id} style={{ borderBottom: '1px solid #f0f0f0', paddingBottom: 10 }}>
              <Space wrap size={[8, 4]}>
                <Tag color={row.direction === 'outbound' ? 'blue' : 'purple'}>
                  {row.direction === 'outbound' ? t('comp.relations.outbound') : t('comp.relations.inbound')}
                </Tag>
                <Tag>{row.relation_name}</Tag>
                <Link to={recordPath(row.counterpart)}>{row.counterpart.code}</Link>
                <Typography.Text>{row.counterpart.title}</Typography.Text>
              </Space>
              <Typography.Paragraph type="secondary" style={{ margin: '6px 0 0', whiteSpace: 'pre-wrap' }}>
                {row.reason}
              </Typography.Paragraph>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {t('comp.relations.createdBy', {
                  name: row.created_by_name || '-',
                  time: row.created_at ? dayjs(row.created_at).format('YYYY-MM-DD HH:mm') : '-',
                })}
              </Typography.Text>
            </div>
          ))}
        </Space>
      )}
    </Card>
  );
}
