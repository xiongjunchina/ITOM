import type { CSSProperties } from 'react';
import { Alert, Tag, Tooltip } from 'antd';
import { useT } from '../i18n';

/**
 * M5.1 示例数据（is_example=true）通用展示组件。
 * 后端对示例记录强制只读（编辑/业务写操作返回 403 EXAMPLE_READONLY），
 * 系统管理员可在列表页使用删除动作清理示例记录；
 * 示例记录的字段值本身即该字段的填写指引，供学习参考。
 */

/** 列表行示例徽标：显示在编号/名称旁 */
export function ExampleTag({ style }: { style?: CSSProperties }) {
  const t = useT();
  return (
    <Tooltip title={t('comp.example.tip')}>
      <Tag color="gold" style={{ marginInlineEnd: 0, ...style }}>
        {t('comp.example.tag')}
      </Tag>
    </Tooltip>
  );
}

/** 详情页顶部示例提示 */
export function ExampleAlert() {
  const t = useT();
  return <Alert type="info" showIcon message={t('comp.example.alert')} />;
}
