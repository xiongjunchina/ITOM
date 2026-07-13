import { useMemo } from 'react';
import { Tag, Tooltip, Typography } from 'antd';
import dayjs, { Dayjs } from 'dayjs';
import type { WbsStatus, WbsTask } from '../api/types';
import { useT } from '../i18n';
import { useLangStore } from '../i18n/store';
import { useEnums } from '../i18n/enums';

/**
 * 自研轻量甘特图（纯 CSS / 绝对定位，无第三方图库），按「甘特图」子表结构：
 * - 左侧 6 列固定（sticky）：WBS编号 / 任务名称 / 责任人 / 计划开始 / 计划结束 / 状态；
 * - 时间轴按周分桶：项目起始周一起，每列 = 1 周（7 天），双行表头（月份行 + 周行）；
 * - 每行蓝色「计划工期」条（start→end）+ 按状态着色的实际条（已完成绿/进行中黄/已延期红/未开始不画）；
 * - 里程碑（is_milestone）在计划结束位置画 ◆（已完成绿/已延期红/其余蓝）；
 * - 今日红色竖线贯穿所有行；容器横向滚动，左 6 列 sticky、表头 sticky top。
 */

interface GanttChartProps {
  tasks: WbsTask[];
  /** 项目计划开始/结束（参与范围计算，保证空任务时也有坐标轴） */
  rangeStart?: string | null;
  rangeEnd?: string | null;
}

const WEEK_W = 40; // 单周列宽
const ROW_H = 36;
const HEADER_MONTH_H = 24;
const HEADER_WEEK_H = 24;
const HEADER_H = HEADER_MONTH_H + HEADER_WEEK_H;
const PLAN_H = 12; // 计划条高
const ACTUAL_H = 6; // 实际条高（更细，下移叠加）

// 颜色
const C_PLAN = '#1677ff';
const C_DONE = '#52c41a';
const C_DOING = '#faad14';
const C_OVERDUE = '#ff4d4f';
const C_TODAY = '#ff4d4f';

// 状态 → antd Tag 颜色（与 ProjectDetail 的 WBS 表保持一致）
const TAG_COLOR: Record<WbsStatus, string> = {
  未开始: 'default',
  进行中: 'processing',
  已完成: 'success',
  已延期: 'error',
};

// 左侧固定列定义（宽度）
const COLS = [
  { key: 'code', w: 96 },
  { key: 'name', w: 200 },
  { key: 'owner', w: 96 },
  { key: 'plannedStart', w: 100 },
  { key: 'plannedEnd', w: 100 },
  { key: 'status', w: 96 },
] as const;
const LEFT_W = COLS.reduce((s, c) => s + c.w, 0);

interface FlatRow {
  task: WbsTask;
  depth: number;
}

/** 按树结构（parent_task_id）先序展开，孤儿节点视为根，depth 用于 WBS 编号缩进 */
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

export default function GanttChart({ tasks, rangeStart, rangeEnd }: GanttChartProps) {
  const t = useT();
  const et = useEnums();
  const lang = useLangStore((s) => s.lang);
  const rows = useMemo(() => flattenTree(tasks), [tasks]);

  const model = useMemo(() => {
    const today = dayjs().startOf('day');
    const starts: Dayjs[] = [today];
    const ends: Dayjs[] = [today];
    const push = (arr: Dayjs[], v?: string | null) => {
      if (!v) return;
      const d = dayjs(v);
      if (d.isValid()) arr.push(d.startOf('day'));
    };
    push(starts, rangeStart);
    push(ends, rangeEnd);
    tasks.forEach((tk) => {
      push(starts, tk.start_date);
      push(ends, tk.end_date);
      push(starts, tk.actual_start);
      push(ends, tk.actual_end);
    });
    let min = starts[0];
    starts.forEach((d) => {
      if (d.isBefore(min)) min = d;
    });
    let max = ends[0];
    ends.forEach((d) => {
      if (d.isAfter(max)) max = d;
    });
    if (max.isBefore(min)) max = min;

    // 起始周一 = min 所在周的周一（dayjs：day()=0 周日, 1 周一 … 6 周六）
    const dow = min.day();
    const axisStart = min.subtract(dow === 0 ? 6 : dow - 1, 'day').startOf('day');
    const weekCount = Math.max(1, Math.ceil((max.diff(axisStart, 'day') + 1) / 7));
    const weeks = Array.from({ length: weekCount }, (_, i) => axisStart.add(i * 7, 'day'));
    const chartW = weekCount * WEEK_W;

    const monthMarks: { left: number; label: string }[] = [];
    weeks.forEach((wk, i) => {
      if (i === 0 || wk.month() !== weeks[i - 1].month()) {
        monthMarks.push({
          left: i * WEEK_W,
          label: lang === 'zh' ? `${wk.month() + 1}月` : wk.format('MMM'),
        });
      }
    });

    return { axisStart, weeks, weekCount, chartW, monthMarks, today };
  }, [tasks, rangeStart, rangeEnd, lang]);

  const { axisStart, weeks, chartW, monthMarks, today } = model;
  const dayW = WEEK_W / 7;
  // 日期 → 相对起始周一的像素 x
  const x = (v: string | Dayjs) => dayjs(v).startOf('day').diff(axisStart, 'day') * dayW;

  const totalH = HEADER_H + rows.length * ROW_H;

  // 单元样式（左侧固定列 + 时间区共用）
  const cellStyle = (w: number, h: number, extra?: React.CSSProperties): React.CSSProperties => ({
    flexShrink: 0,
    width: w,
    height: h,
    lineHeight: `${h}px`,
    padding: '0 8px',
    fontSize: 12,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    borderRight: '1px solid #f0f0f0',
    boxSizing: 'border-box',
    ...extra,
  });

  // 左侧固定块（一行 6 列），position: sticky
  const leftBlock = (
    cells: React.ReactNode[],
    h: number,
    strong = false,
    top?: number,
  ): JSX.Element => (
    <div
      style={{
        position: 'sticky',
        left: 0,
        top,
        zIndex: top !== undefined ? 5 : 3,
        display: 'flex',
        flexShrink: 0,
        width: LEFT_W,
        background: '#fff',
        borderBottom: '1px solid #f0f0f0',
        fontWeight: strong ? 600 : 400,
      }}
    >
      {COLS.map((c, i) => (
        <div key={c.key} style={cellStyle(c.w, h, { fontWeight: strong ? 600 : 400 })}>
          {cells[i]}
        </div>
      ))}
    </div>
  );

  const legendItem = (color: string, label: string, shape: 'bar' | 'diamond' | 'line') => (
    <span key={label} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      {shape === 'diamond' ? (
        <span style={{ display: 'inline-block', width: 8, height: 8, background: color, transform: 'rotate(45deg)' }} />
      ) : shape === 'line' ? (
        <span style={{ display: 'inline-block', width: 0, height: 12, borderLeft: `2px solid ${color}` }} />
      ) : (
        <span style={{ display: 'inline-block', width: 14, height: 8, borderRadius: 2, background: color }} />
      )}
      {label}
    </span>
  );

  return (
    <div>
      {/* 图例 */}
      <div
        style={{
          display: 'flex',
          gap: 16,
          flexWrap: 'wrap',
          marginBottom: 8,
          fontSize: 12,
          color: 'rgba(0,0,0,0.65)',
        }}
      >
        {legendItem(C_PLAN, t('proj.gantt.legend.plan'), 'bar')}
        {legendItem(C_DONE, t('proj.gantt.legend.actualDone'), 'bar')}
        {legendItem(C_DOING, t('proj.gantt.legend.actualDoing'), 'bar')}
        {legendItem(C_OVERDUE, t('proj.gantt.legend.overdue'), 'bar')}
        {legendItem(C_PLAN, t('proj.gantt.legend.milestone'), 'diamond')}
        {legendItem(C_TODAY, t('proj.gantt.legend.today'), 'line')}
      </div>

      <div style={{ overflowX: 'auto', border: '1px solid #f0f0f0', borderRadius: 8, maxHeight: 560, overflowY: 'auto' }}>
        <div style={{ position: 'relative', width: LEFT_W + chartW, minWidth: '100%' }}>
          {/* 周网格竖线（压在图表区底层，左侧列白底盖住） */}
          {weeks.map((_, i) => (
            <div
              key={`grid-${i}`}
              style={{
                position: 'absolute',
                left: LEFT_W + i * WEEK_W,
                top: 0,
                height: totalH,
                borderLeft: '1px solid #f5f5f5',
                zIndex: 0,
              }}
            />
          ))}

          {/* 表头：月份行 + 周行 */}
          <div style={{ display: 'flex', position: 'sticky', top: 0, zIndex: 4 }}>
            {leftBlock(
              [
                t('proj.gantt.col.code'),
                t('proj.gantt.col.name'),
                t('proj.gantt.col.owner'),
                t('proj.gantt.col.plannedStart'),
                t('proj.gantt.col.plannedEnd'),
                t('proj.gantt.col.status'),
              ].map((s, i) => (
                <span key={i} style={{ lineHeight: `${HEADER_H}px` }}>
                  {s}
                </span>
              )),
              HEADER_H,
              true,
              0,
            )}
            <div style={{ position: 'relative', width: chartW, height: HEADER_H, background: '#fff', borderBottom: '1px solid #f0f0f0' }}>
              {/* 月份行 */}
              {monthMarks.map((m, i) => (
                <span
                  key={`mon-${i}`}
                  style={{
                    position: 'absolute',
                    left: m.left + 2,
                    top: 0,
                    height: HEADER_MONTH_H,
                    lineHeight: `${HEADER_MONTH_H}px`,
                    fontSize: 12,
                    fontWeight: 600,
                    color: 'rgba(0,0,0,0.65)',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {m.label}
                </span>
              ))}
              {/* 周行 */}
              {weeks.map((wk, i) => (
                <span
                  key={`wk-${i}`}
                  style={{
                    position: 'absolute',
                    left: i * WEEK_W,
                    top: HEADER_MONTH_H,
                    width: WEEK_W,
                    height: HEADER_WEEK_H,
                    lineHeight: `${HEADER_WEEK_H}px`,
                    textAlign: 'center',
                    fontSize: 11,
                    color: 'rgba(0,0,0,0.45)',
                    borderTop: '1px solid #f5f5f5',
                    boxSizing: 'border-box',
                  }}
                >
                  {wk.format('M/D')}
                </span>
              ))}
            </div>
          </div>

          {/* 任务行 */}
          {rows.map(({ task, depth }) => {
            const status = task.status;
            const isMs = task.is_milestone;

            // 计划条
            const planLeft = x(task.start_date);
            const planW = Math.max(x(task.end_date) - planLeft, 4);

            // 实际条（按状态）
            let actual: { left: number; width: number; color: string } | null = null;
            if (status === '已完成') {
              const s = task.actual_start ?? task.start_date;
              const e = task.actual_end ?? task.end_date;
              actual = { left: x(s), width: Math.max(x(e) - x(s), 4), color: C_DONE };
            } else if (status === '进行中') {
              const s = task.actual_start ?? task.start_date;
              actual = { left: x(s), width: Math.max(x(today) - x(s), 4), color: C_DOING };
            } else if (status === '已延期') {
              actual = { left: planLeft, width: Math.max(x(today) - planLeft, 4), color: C_OVERDUE };
            }

            const msColor = status === '已完成' ? C_DONE : status === '已延期' ? C_OVERDUE : C_PLAN;

            const tip = (
              <div style={{ fontSize: 12 }}>
                <div style={{ fontWeight: 600 }}>
                  {task.wbs_code} {task.name}
                </div>
                <div>
                  {t('proj.gantt.tip.planned')}: {task.start_date} ~ {task.end_date}
                </div>
                {(task.actual_start || task.actual_end) && (
                  <div>
                    {t('proj.gantt.tip.actual')}: {task.actual_start ?? '-'} ~ {task.actual_end ?? '-'}
                  </div>
                )}
                <div>
                  {t('proj.gantt.tip.status')}: {et.wbsStatus(status)}
                </div>
              </div>
            );

            return (
              <div key={task.id} style={{ display: 'flex', position: 'relative', zIndex: 1 }}>
                {leftBlock(
                  [
                    <span key="c" style={{ paddingLeft: depth * 12, color: 'rgba(0,0,0,0.55)' }}>
                      {task.wbs_code}
                    </span>,
                    <span key="n">
                      {isMs && <span style={{ color: C_PLAN, marginRight: 4 }}>◆</span>}
                      {task.name}
                    </span>,
                    <span key="o">{task.assignee_name || '-'}</span>,
                    <span key="ps">{task.start_date || '-'}</span>,
                    <span key="pe">{task.end_date || '-'}</span>,
                    <Tag key="st" color={TAG_COLOR[status] ?? 'default'} style={{ marginInlineEnd: 0 }}>
                      {et.wbsStatus(status)}
                    </Tag>,
                  ],
                  ROW_H,
                )}
                <div
                  style={{
                    position: 'relative',
                    width: chartW,
                    height: ROW_H,
                    borderBottom: '1px solid #f0f0f0',
                  }}
                >
                  <Tooltip title={tip}>
                    <div style={{ position: 'absolute', inset: 0 }}>
                      {isMs ? (
                        // 里程碑：在计划结束位置画 ◆（以计划结束定位）
                        <span
                          style={{
                            position: 'absolute',
                            left: x(task.end_date) - 6,
                            top: (ROW_H - 12) / 2,
                            width: 12,
                            height: 12,
                            background: msColor,
                            transform: 'rotate(45deg)',
                          }}
                        />
                      ) : (
                        <>
                          {/* 计划条（蓝） */}
                          <div
                            style={{
                              position: 'absolute',
                              left: planLeft,
                              top: 8,
                              width: planW,
                              height: PLAN_H,
                              borderRadius: 3,
                              background: C_PLAN,
                            }}
                          />
                          {/* 实际条（按状态着色，下移叠加） */}
                          {actual && (
                            <div
                              style={{
                                position: 'absolute',
                                left: actual.left,
                                top: 8 + PLAN_H + 1,
                                width: actual.width,
                                height: ACTUAL_H,
                                borderRadius: 3,
                                background: actual.color,
                              }}
                            />
                          )}
                        </>
                      )}
                    </div>
                  </Tooltip>
                </div>
              </div>
            );
          })}

          {/* 今日红色竖线（贯穿所有行） */}
          <div
            style={{
              position: 'absolute',
              left: LEFT_W + x(today),
              top: HEADER_MONTH_H,
              height: totalH - HEADER_MONTH_H,
              borderLeft: `2px solid ${C_TODAY}`,
              zIndex: 2,
              pointerEvents: 'none',
            }}
          >
            <span
              style={{
                position: 'absolute',
                top: 0,
                left: 2,
                fontSize: 10,
                color: C_TODAY,
                whiteSpace: 'nowrap',
                lineHeight: `${HEADER_WEEK_H}px`,
              }}
            >
              {t('proj.gantt.legend.today')}
            </span>
          </div>

          {rows.length === 0 && (
            <div
              style={{
                display: 'flex',
                position: 'relative',
                zIndex: 1,
              }}
            >
              {leftBlock([<Typography.Text key="e" type="secondary">{t('proj.gantt.empty')}</Typography.Text>, '', '', '', '', ''], ROW_H)}
              <div style={{ width: chartW, height: ROW_H, borderBottom: '1px solid #f0f0f0' }} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
