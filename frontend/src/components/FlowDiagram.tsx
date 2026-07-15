import type { CSSProperties } from 'react';
import { Button, Tag, Typography } from 'antd';
import { CheckOutlined, SoundOutlined, UserOutlined } from '@ant-design/icons';
import { canHandleTask, useAuthStore } from '../stores/auth';
import { useT } from '../i18n';
import { useEnums } from '../i18n/enums';

/** 流程示意图单步（兼容定义视图 ProcessStepDef 与实例视图 ProcessStep） */
export interface FlowDiagramStep {
  seq: number;
  name: string;
  default_role?: string | null;
  cc_roles?: string[] | null;
  autonomy_level?: string | null;
  sla_hours?: number | null;
  /** 步骤说明（如实现交付节点的两条路径说明），有则在节点内灰字展示 */
  description?: string | null;
  /** 实例视图字段（定义预览无）：有待处理任务时可渲染「完成此步骤」入口 */
  task_id?: string | null;
  task_status?: string | null;
  /** 处理人 person id：完成按钮仅任务处理人本人或 admin 可见（M18） */
  assignee?: string | null;
  assignee_name?: string | null;
}

interface FlowDiagramProps {
  steps: FlowDiagramStep[];
  /** 把角色 code / "group:组码" 转中文名 */
  roleLabel: (key: string) => string;
  /** 当前步骤 seq：匹配节点高亮（蓝色边框） */
  currentSeq?: number | null;
  /** 完成步骤回调（实例视图传入）：待处理步骤显示「完成此步骤」按钮，推进流程到下一节点 */
  onCompleteStep?: (step: FlowDiagramStep) => void;
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
export default function FlowDiagram({ steps, roleLabel, currentSeq, onCompleteStep }: FlowDiagramProps) {
  const t = useT();
  const et = useEnums();
  const user = useAuthStore((s) => s.user);
  if (!steps || steps.length === 0) {
    return <Typography.Text type="secondary">{t('comp.flow.noStep')}</Typography.Text>;
  }
  return (
    <div style={{ overflowX: 'auto', padding: '2px 0' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', rowGap: 8 }}>
        {steps.map((s, i) => {
          const isCurrent = currentSeq != null && s.seq === currentSeq;
          const cc = (s.cc_roles ?? []).filter(Boolean);
          const notes: string[] = [];
          if (s.autonomy_level) {
            notes.push(et.autonomy(s.autonomy_level));
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
                    {s.name || t('comp.flow.unnamed')}
                  </Typography.Text>
                </div>
                {/* 处理人 */}
                <div style={{ marginTop: 6 }}>
                  <Tag icon={<UserOutlined />} color="blue" style={{ marginInlineEnd: 0 }}>
                    {s.assignee_name ?? (s.default_role ? roleLabel(s.default_role) : t('comp.flow.unassigned'))}
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
                        {t('comp.flow.cc', { name: roleLabel(k) })}
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
                {/* 步骤说明（路径分支等），灰字小号 */}
                {s.description && (
                  <div style={{ marginTop: 4, maxWidth: 260 }}>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {s.description}
                    </Typography.Text>
                  </div>
                )}
                {/* 待处理步骤的推进入口（仅实例视图且当前用户是任务处理人或 admin，M18） */}
                {onCompleteStep && s.task_id && s.task_status === '待处理' && canHandleTask(user, s) && (
                  <div style={{ marginTop: 6 }}>
                    <Button size="small" type="primary" ghost icon={<CheckOutlined />} onClick={() => onCompleteStep(s)}>
                      {t('comp.flow.completeStep')}
                    </Button>
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
