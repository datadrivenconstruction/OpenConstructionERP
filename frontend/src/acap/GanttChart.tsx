/**
 * Native React SVG Gantt chart for the ACAP construction timeline.
 *
 * Purely presentational - no fetching, no state. Mirrors the "native SVG,
 * no chart library" stance of FloorPlanEditor.tsx: one <rect> per task bar,
 * grouped/colored by stage, on a working-day axis (day 0 = project start).
 */

import type { TimelineStage, TimelineTask } from './timelineApi';
import { dayToX, durationToWidth, PX_PER_DAY } from './ganttScale';

const ROW_HEIGHT = 28;
const HEADER_HEIGHT = 32;
const GUTTER_WIDTH = 260;
const BAR_HEIGHT = 18;

/** Fixed palette cycled by first-seen stage order - stage names are
 *  free-form strings from the backend, not a closed TS union, so this
 *  can't be a Record keyed by stage like FloorPlanEditor's ROOM_COLORS. */
const STAGE_PALETTE = [
  '#a5b4fc', '#fdba74', '#7dd3fc', '#fca5a5', '#86efac',
  '#fde68a', '#c4b5fd', '#f9a8d4', '#5eead4', '#fcd34d',
];

function stageColor(stage: string, order: string[]): string {
  const idx = order.indexOf(stage);
  return STAGE_PALETTE[idx % STAGE_PALETTE.length] ?? STAGE_PALETTE[0]!;
}

/** Pick a day-tick interval so the header doesn't get cluttered on long
 *  schedules (e.g. a 200-day project doesn't render 200 labels). */
function tickInterval(totalDays: number): number {
  if (totalDays <= 30) return 5;
  if (totalDays <= 90) return 10;
  return 20;
}

export interface GanttChartProps {
  tasks: TimelineTask[];
  stages: TimelineStage[];
  totalDays: number;
}

export function GanttChart({ tasks, stages, totalDays }: GanttChartProps) {
  if (tasks.length === 0) {
    return <div className="p-6 text-sm text-content-tertiary">Belum ada timeline.</div>;
  }

  const stageOrder = stages.length > 0 ? stages.map((s) => s.stage) : Array.from(new Set(tasks.map((t) => t.stage)));

  const chartWidth = GUTTER_WIDTH + Math.max(totalDays, 1) * PX_PER_DAY + PX_PER_DAY;
  const chartHeight = HEADER_HEIGHT + tasks.length * ROW_HEIGHT;

  const ticks: number[] = [];
  const step = tickInterval(totalDays);
  for (let d = 0; d <= totalDays; d += step) ticks.push(d);

  return (
    <div className="flex flex-col gap-2">
      <div className="text-sm font-medium text-content-primary">
        Total durasi: <span className="text-oe-blue">{totalDays}</span> hari kerja
      </div>
      <div className="w-full overflow-x-auto rounded-md border border-border bg-surface-secondary">
        <svg width={chartWidth} height={chartHeight} role="img" aria-label="Timeline konstruksi">
          {/* Header day-axis */}
          <g>
            {ticks.map((d) => (
              <g key={d}>
                <line
                  x1={GUTTER_WIDTH + dayToX(d)}
                  y1={0}
                  x2={GUTTER_WIDTH + dayToX(d)}
                  y2={chartHeight}
                  stroke="currentColor"
                  className="text-border"
                  strokeWidth={1}
                />
                <text
                  x={GUTTER_WIDTH + dayToX(d) + 3}
                  y={14}
                  fontSize={10}
                  fill="currentColor"
                  className="text-content-tertiary"
                >
                  {d}d
                </text>
              </g>
            ))}
          </g>

          {/* Gutter / header divider */}
          <line x1={GUTTER_WIDTH} y1={0} x2={GUTTER_WIDTH} y2={chartHeight} stroke="currentColor" className="text-border" strokeWidth={1.5} />
          <line x1={0} y1={HEADER_HEIGHT} x2={chartWidth} y2={HEADER_HEIGHT} stroke="currentColor" className="text-border" strokeWidth={1} />

          {/* Rows */}
          {tasks.map((task, i) => {
            const y = HEADER_HEIGHT + i * ROW_HEIGHT;
            const barY = y + (ROW_HEIGHT - BAR_HEIGHT) / 2;
            const color = stageColor(task.stage, stageOrder);
            return (
              <g key={`${task.kode}-${i}`}>
                {i % 2 === 1 && (
                  <rect x={0} y={y} width={chartWidth} height={ROW_HEIGHT} fill="currentColor" className="text-surface-primary" opacity={0.4} />
                )}
                <text
                  x={8}
                  y={y + ROW_HEIGHT / 2 + 4}
                  fontSize={11}
                  fill="currentColor"
                  className="text-content-primary"
                >
                  <title>{task.kode}</title>
                  {truncate(task.uraian || task.kode, 34)}
                </text>
                <rect
                  x={GUTTER_WIDTH + dayToX(task.start_day)}
                  y={barY}
                  width={Math.max(durationToWidth(task.duration_days), 1)}
                  height={BAR_HEIGHT}
                  rx={3}
                  fill={color}
                  stroke="#1f2937"
                  strokeWidth={0.5}
                >
                  <title>{`${task.uraian} (${task.stage}) - ${task.duration_days}d, hari ${task.start_day}-${task.end_day}`}</title>
                </rect>
                <text
                  x={GUTTER_WIDTH + dayToX(task.start_day) + Math.max(durationToWidth(task.duration_days), 1) + 4}
                  y={y + ROW_HEIGHT / 2 + 4}
                  fontSize={10}
                  fill="currentColor"
                  className="text-content-tertiary pointer-events-none"
                >
                  {task.duration_days}d
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

function truncate(s: string, max: number): string {
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}
