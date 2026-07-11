import type { CSSProperties } from 'react';
import { Tag, Typography } from 'antd';
import { SoundOutlined, UserOutlined } from '@ant-design/icons';
import { AUTONOMY_LABELS } from '../api/types';

/** 流程示意图单步（兼容定义视图 ProcessStepDef 与实例视图 ProcessStep） */
export interface FlowDiagramStep {
  seq: number;
  name: string;
  default_role?: string | null;
  cc_roles?: string[] | null;
  autonomy_level?: string | null;
  sla_hours?: number | null;
}

interface FlowDiagramProps {
  steps: FlowDiagramStep[];
  /** 把角色 code / "group:组码" 转中文名 */
  roleLabel: (key: string) => string;
  /** 当前步骤 seq：匹配节点高亮（蓝色边框） */
  currentSeq?: number | null;
}

const CARD_BASE: CSSProperties = {
  border: '1px solid #d9d9d9',
  borderRadius: 8,
  padding: '8px 12px',
  background: '#fff',
  minWidth: 148,
  maxWidth: 280,
};

const CARD_CURRENT: CSSProperties = {
  ...CARD_BASE,
  border: '1px solid #1677ff',
  boxShadow: '0 0 0 1px #1677ff inset',
};

/**
 * 流程示意图（通用复用）：横向节点链 + 箭头，可换行。
 * 每个节点展示：序号 + 步骤名 / 处理人（蓝 Tag）/ 知会人（灰 Tag 列表）/ 自治级别·SLA 附注。
 * 纯 CSS/antd 实现，不依赖第三方图库。
 */
export default function FlowDiagram({ steps, roleLabel, currentSeq }: FlowDiagramProps) {
  if (!steps || steps.length === 0) {
    return <Typography.Text type="secondary">暂无步骤</Typography.Text>;
  }
  return (
    <div style={{ overflowX: 'auto', padding: '2px 0' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', rowGap: 8 }}>
        {steps.map((s, i) => {
          const isCurrent = currentSeq != null && s.seq === currentSeq;
          const cc = (s.cc_roles ?? []).filter(Boolean);
          const notes: string[] = [];
          if (s.autonomy_level) {
            notes.push(
              (AUTONOMY_LABELS as Record<string, string>)[s.autonomy_level] ?? s.autonomy_level,
            );
          }
          if (s.sla_hours != null) {
            notes.push(`SLA ${s.sla_hours}h`);
          }
          return (
            <div key={`${s.seq}-${i}`} style={{ display: 'flex', alignItems: 'center' }}>
              <div style={isCurrent ? CARD_CURRENT : CARD_BASE}>
                {/* 序号 + 步骤名 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span
                    style={{
                      flexShrink: 0,
                      width: 18,
                      height: 18,
                      lineHeight: '18px',
                      borderRadius: '50%',
                      textAlign: 'center',
                      fontSize: 12,
                      background: isCurrent ? '#1677ff' : 'rgba(0,0,0,0.06)',
                      color: isCurrent ? '#fff' : 'rgba(0,0,0,0.65)',
                    }}
                  >
                    {s.seq}
                  </span>
                  <Typography.Text strong style={{ fontSize: 13 }}>
                    {s.name || '（未命名）'}
                  </Typography.Text>
                </div>
                {/* 处理人 */}
                <div style={{ marginTop: 6 }}>
                  <Tag icon={<UserOutlined />} color="blue" style={{ marginInlineEnd: 0 }}>
                    {s.default_role ? roleLabel(s.default_role) : '未指派'}
                  </Tag>
                </div>
                {/* 知会人（有才显示） */}
                {cc.length > 0 && (
                  <div style={{ marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {cc.map((k) => (
                      <Tag
                        key={k}
                        icon={<SoundOutlined />}
                        style={{ marginInlineEnd: 0, color: 'rgba(0,0,0,0.45)' }}
                      >
                        知会 {roleLabel(k)}
                      </Tag>
                    ))}
                  </div>
                )}
                {/* 附注：自治级别 + SLA（有才显示） */}
                {notes.length > 0 && (
                  <div style={{ marginTop: 4 }}>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {notes.join(' · ')}
                    </Typography.Text>
                  </div>
                )}
              </div>
              {i < steps.length - 1 && (
                <span
                  aria-hidden
                  style={{ margin: '0 8px', color: '#bfbfbf', fontSize: 14, flexShrink: 0 }}
                >
                  →
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
