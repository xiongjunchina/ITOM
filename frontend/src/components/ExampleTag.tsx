import type { CSSProperties } from 'react';
import { Alert, Tag, Tooltip } from 'antd';

/**
 * M5.1 示例数据（is_example=true）通用展示组件。
 * 后端对示例记录强制只读（写操作返回 403 EXAMPLE_READONLY），
 * 示例记录的字段值本身即该字段的填写指引，供学习参考。
 */

const EXAMPLE_TIP = '示例数据：字段内容即填写指引，仅供学习参考，不可编辑';

/** 列表行示例徽标：显示在编号/名称旁 */
export function ExampleTag({ style }: { style?: CSSProperties }) {
  return (
    <Tooltip title={EXAMPLE_TIP}>
      <Tag color="gold" style={{ marginInlineEnd: 0, ...style }}>
        示例
      </Tag>
    </Tooltip>
  );
}

/** 详情页顶部示例提示 */
export function ExampleAlert() {
  return (
    <Alert
      type="info"
      showIcon
      message="这是一条示例数据——每个字段的内容就是该字段的填写指引，仅供学习参考，不可编辑。"
    />
  );
}
