import { useMemo } from 'react';
import { Tooltip, Typography } from 'antd';
import dayjs, { Dayjs } from 'dayjs';
import type { Milestone, WbsTask } from '../api/types';
import { WBS_STATUS_COLORS } from '../api/types';

/**
 * 自研轻量甘特图（纯 CSS / 绝对定位，无第三方图库）：
 * - 横轴按项目计划起止（并入任务/里程碑日期）确定日期范围，短周期按周刻度、长周期按月刻度；
 * - 每个任务一行水平条，按起止日期定位，状态着色（未开始灰 / 进行中蓝 / 已完成绿）；
 * - 里程碑用菱形标记在对应日期（达成绿 / 逾期红 / 未达成蓝）；
 * - 今日红色竖线；容器横向滚动，任务名列 sticky 固定在左侧。
 */

interface GanttChartProps {
  tasks: WbsTask[];
  milestones?: Milestone[];
  /** 项目计划开始/结束（参与范围计算，保证空任务时也有坐标轴） */
  rangeStart?: string | null;
  rangeEnd?: string | null;
}

const LABEL_W = 220;
const HEADER_H = 30;
const ROW_H = 32;
const BAR_H = 16;

interface FlatRow {
  task: WbsTask;
  depth: number;
}

/** 按树结构（parent_task_id）先序展开，孤儿节点视为根 */
function flattenTree(tasks: WbsTask[]): FlatRow[] {
  const ids = new Set(tasks.map((t) => t.id));
  const byParent = new Map<string, WbsTask[]>();
  tasks.forEach((t) => {
    const key = t.parent_task_id && ids.has(t.parent_task_id) ? t.parent_task_id : '';
    const list = byParent.get(key) ?? [];
    list.push(t);
    byParent.set(key, list);
  });
  const out: FlatRow[] = [];
  const walk = (parentKey: string, depth: number) => {
    (byParent.get(parentKey) ?? []).forEach((t) => {
      out.push({ task: t, depth });
      walk(t.id, depth + 1);
    });
  };
  walk('', 0);
  return out;
}

export default function GanttChart({ tasks, milestones = [], rangeStart, rangeEnd }: GanttChartProps) {
  const rows = useMemo(() => flattenTree(tasks), [tasks]);

  const model = useMemo(() => {
    const dates: Dayjs[] = [];
    const push = (v?: string | null) => {
      if (!v) return;
      const d = dayjs(v);
      if (d.isValid()) dates.push(d);
    };
    push(rangeStart);
    push(rangeEnd);
    tasks.forEach((t) => {
      push(t.start_date);
      push(t.end_date);
    });
    milestones.forEach((m) => push(m.target_date));
    if (dates.length === 0) return null;

    let min = dates[0];
    let max = dates[0];
    dates.forEach((d) => {
      if (d.isBefore(min)) min = d;
      if (d.isAfter(max)) max = d;
    });
    // 两端各留 3 天呼吸空间
    min = min.subtract(3, 'day').startOf('day');
    max = max.add(3, 'day').startOf('day');
    const totalDays = max.diff(min, 'day') + 1;
    // 短周期按周刻度（日宽大），长周期按月刻度（日宽小）
    const weekMode = totalDays <= 130;
    const dayWidth = weekMode ? 18 : 5;

    const ticks: { left: number; label: string }[] = [];
    if (weekMode) {
      // 每周一一条刻度线
      let cur = min.day() === 1 ? min : min.add((8 - min.day()) % 7 || 7, 'day');
      while (!cur.isAfter(max)) {
        ticks.push({ left: cur.diff(min, 'day') * dayWidth, label: cur.format('MM-DD') });
        cur = cur.add(7, 'day');
      }
    } else {
      // 每月 1 日一条刻度线
      let cur = min.date() === 1 ? min : min.add(1, 'month').startOf('month');
      while (!cur.isAfter(max)) {
        ticks.push({ left: cur.diff(min, 'day') * dayWidth, label: cur.format('YYYY-MM') });
        cur = cur.add(1, 'month');
      }
    }
    return { min, max, dayWidth, chartW: totalDays * dayWidth, ticks };
  }, [tasks, milestones, rangeStart, rangeEnd]);

  if (!model || (rows.length === 0 && milestones.length === 0)) {
    return <Typography.Text type="secondary">暂无任务或里程碑，无法绘制甘特图</Typography.Text>;
  }

  const { min, max, dayWidth, chartW, ticks } = model;
  const offsetOf = (v: string) => dayjs(v).diff(min, 'day') * dayWidth;
  const hasMsRow = milestones.length > 0;
  const bodyTop = HEADER_H + (hasMsRow ? ROW_H : 0);
  const totalH = bodyTop + rows.length * ROW_H;
  const today = dayjs().startOf('day');
  const todayVisible = !today.isBefore(min) && !today.isAfter(max);

  const labelCell = (content: React.ReactNode, height: number, strong = false): JSX.Element => (
    <div
      style={{
        position: 'sticky',
        left: 0,
        zIndex: 3,
        flexShrink: 0,
        width: LABEL_W,
        height,
        lineHeight: `${height}px`,
        padding: '0 8px',
        background: '#fff',
        borderRight: '1px solid #f0f0f0',
        borderBottom: '1px solid #f0f0f0',
        fontSize: 13,
        fontWeight: strong ? 600 : 400,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
      }}
    >
      {content}
    </div>
  );

  return (
    <div>
      {/* 图例 */}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 8, fontSize: 12, color: 'rgba(0,0,0,0.65)' }}>
        {(['未开始', '进行中', '已完成'] as const).map((s) => (
          <span key={s}>
            <span
              style={{
                display: 'inline-block',
                width: 12,
                height: 8,
                borderRadius: 2,
                background: WBS_STATUS_COLORS[s],
                marginRight: 4,
              }}
            />
            {s}
          </span>
        ))}
        <span>
          <span
            style={{
              display: 'inline-block',
              width: 8,
              height: 8,
              background: '#1677ff',
              transform: 'rotate(45deg)',
              marginRight: 6,
            }}
          />
          里程碑（绿=达成 / 红=逾期）
        </span>
        <span>
          <span
            style={{
              display: 'inline-block',
              width: 0,
              height: 10,
              borderLeft: '2px solid #ff4d4f',
              marginRight: 4,
              verticalAlign: 'middle',
            }}
          />
          今日
        </span>
      </div>

      <div style={{ overflowX: 'auto', border: '1px solid #f0f0f0', borderRadius: 8 }}>
        <div style={{ position: 'relative', width: LABEL_W + chartW, minWidth: '100%' }}>
          {/* 刻度竖线（压在图表区，标签列 sticky 白底盖住它） */}
          {ticks.map((t, i) => (
            <div
              key={`grid-${i}`}
              style={{
                position: 'absolute',
                left: LABEL_W + t.left,
                top: 0,
                height: totalH,
                borderLeft: '1px solid #f0f0f0',
                zIndex: 0,
              }}
            />
          ))}

          {/* 表头：刻度标签 */}
          <div style={{ display: 'flex', position: 'relative', zIndex: 1 }}>
            {labelCell('任务', HEADER_H, true)}
            <div style={{ position: 'relative', width: chartW, height: HEADER_H, borderBottom: '1px solid #f0f0f0' }}>
              {ticks.map((t, i) => (
                <span
                  key={`tick-${i}`}
                  style={{
                    position: 'absolute',
                    left: t.left + 3,
                    top: 6,
                    fontSize: 12,
                    color: 'rgba(0,0,0,0.45)',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {t.label}
                </span>
              ))}
            </div>
          </div>

          {/* 里程碑行 */}
          {hasMsRow && (
            <div style={{ display: 'flex', position: 'relative', zIndex: 1 }}>
              {labelCell('里程碑', ROW_H, true)}
              <div style={{ position: 'relative', width: chartW, height: ROW_H, borderBottom: '1px solid #f0f0f0' }}>
                {milestones.map((m) => {
                  const color = m.achieved_at ? '#52c41a' : m.overdue ? '#ff4d4f' : '#1677ff';
                  const state = m.achieved_at ? `已达成（${m.achieved_at}）` : m.overdue ? '已逾期' : '未达成';
                  return (
                    <Tooltip key={m.id} title={`${m.name} · ${m.target_date} · ${state}`}>
                      <span
                        style={{
                          position: 'absolute',
                          left: offsetOf(m.target_date) - 5,
                          top: (ROW_H - 10) / 2,
                          width: 10,
                          height: 10,
                          background: color,
                          transform: 'rotate(45deg)',
                          cursor: 'default',
                        }}
                      />
                    </Tooltip>
                  );
                })}
              </div>
            </div>
          )}

          {/* 任务行 */}
          {rows.map(({ task, depth }) => {
            const left = offsetOf(task.start_date);
            const width = Math.max(
              (dayjs(task.end_date).diff(dayjs(task.start_date), 'day') + 1) * dayWidth - 1,
              5,
            );
            return (
              <div key={task.id} style={{ display: 'flex', position: 'relative', zIndex: 1 }}>
                {labelCell(
                  <span style={{ paddingLeft: depth * 14 }}>
                    <Typography.Text type="secondary" style={{ fontSize: 12, marginRight: 6 }}>
                      {task.wbs_code}
                    </Typography.Text>
                    {task.name}
                  </span>,
                  ROW_H,
                )}
                <div style={{ position: 'relative', width: chartW, height: ROW_H, borderBottom: '1px solid #f0f0f0' }}>
                  <Tooltip
                    title={`${task.wbs_code} ${task.name} · ${task.start_date} ~ ${task.end_date} · ${task.status}${task.assignee_name ? ` · ${task.assignee_name}` : ''}`}
                  >
                    <div
                      style={{
                        position: 'absolute',
                        left,
                        top: (ROW_H - BAR_H) / 2,
                        width,
                        height: BAR_H,
                        borderRadius: 4,
                        background: WBS_STATUS_COLORS[task.status] ?? '#bfbfbf',
                        cursor: 'default',
                      }}
                    />
                  </Tooltip>
                </div>
              </div>
            );
          })}

          {/* 今日红色竖线 */}
          {todayVisible && (
            <div
              style={{
                position: 'absolute',
                left: LABEL_W + today.diff(min, 'day') * dayWidth,
                top: HEADER_H,
                height: totalH - HEADER_H,
                borderLeft: '2px solid #ff4d4f',
                zIndex: 2,
                pointerEvents: 'none',
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
