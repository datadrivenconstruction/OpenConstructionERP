// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The Gantt chart's left table: pickable columns, columns the reader can
 * widen, and a splitter between the table and the chart.
 *
 * Choices live in `useGanttTablePrefsStore`. Every offset is logical (start,
 * end) and a drag is read against the document direction, so the table works
 * mirrored in right-to-left languages.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent, Ref, UIEventHandler } from 'react';
import { useTranslation } from 'react-i18next';
import { Columns3 } from 'lucide-react';
import {
  GANTT_TABLE_MAX_WIDTH,
  GANTT_TABLE_MIN_WIDTH,
  useGanttTablePrefsStore,
} from '@/stores/useGanttTablePrefsStore';
import {
  GANTT_COLUMNS,
  formatPredecessors,
  visibleColumns,
  type GanttColumnDef,
  type GanttColumnId,
} from './ganttColumns';
import type { GanttActivity } from './ganttUtils';

const KEY_STEP = 8;
const KEY_STEP_BIG = 32;
const PICKER_WIDTH = 28;

function isRtl(el: Element | null): boolean {
  return el != null && getComputedStyle(el).direction === 'rtl';
}

/**
 * A drag or arrow-key resize of one edge. Returns handlers to spread on the
 * separator; ``read`` gives the current size, ``write`` receives the new one.
 */
function useEdgeResize(read: () => number, write: (px: number) => void, reset?: () => void) {
  const drag = useRef<{ x: number; size: number; sign: number } | null>(null);

  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    drag.current = { x: e.clientX, size: read(), sign: isRtl(e.currentTarget) ? -1 : 1 };
  };
  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (d) write(d.size + (e.clientX - d.x) * d.sign);
  };
  const onPointerUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    drag.current = null;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
  };
  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    const sign = isRtl(e.currentTarget) ? -1 : 1;
    const step = e.shiftKey ? KEY_STEP_BIG : KEY_STEP;
    if (e.key === 'ArrowRight') write(read() + step * sign);
    else if (e.key === 'ArrowLeft') write(read() - step * sign);
    else if (e.key === 'Home' && reset) reset();
    else return;
    e.preventDefault();
    e.stopPropagation();
  };
  return { onPointerDown, onPointerMove, onPointerUp, onPointerCancel: onPointerUp, onKeyDown };
}

function ColumnResizer({ def, label, current }: { def: GanttColumnDef; label: string; current: () => number }) {
  const setColumnWidth = useGanttTablePrefsStore((s) => s.setColumnWidth);
  const handlers = useEdgeResize(current, (px) => setColumnWidth(def.id, px));
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={current()}
      aria-valuemin={def.minWidth}
      aria-valuemax={def.maxWidth}
      tabIndex={0}
      data-testid={`gantt-col-resize-${def.id}`}
      onClick={(e) => e.stopPropagation()}
      className="absolute inset-y-0 end-0 z-10 w-1.5 cursor-col-resize touch-none hover:bg-oe-blue/40 focus-visible:bg-oe-blue/60 focus-visible:outline-none"
      {...handlers}
    />
  );
}

function ColumnPicker({ selected }: { selected: readonly GanttColumnId[] }) {
  const { t } = useTranslation();
  const toggleColumn = useGanttTablePrefsStore((s) => s.toggleColumn);
  const reset = useGanttTablePrefsStore((s) => s.reset);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onPointer);
    return () => document.removeEventListener('pointerdown', onPointer);
  }, [open]);

  return (
    <div
      ref={rootRef}
      className="relative flex shrink-0 items-end justify-center pb-1"
      style={{ width: PICKER_WIDTH }}
      onKeyDown={(e) => {
        if (e.key === 'Escape' && open) {
          e.stopPropagation();
          setOpen(false);
        }
      }}
    >
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t('gantt.columns', { defaultValue: 'Columns' })}
        title={t('gantt.columns', { defaultValue: 'Columns' })}
        data-testid="gantt-columns-button"
        onClick={() => setOpen((v) => !v)}
        className="rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
      >
        <Columns3 size={14} aria-hidden />
      </button>
      {open && (
        <div
          role="menu"
          aria-label={t('gantt.columns', { defaultValue: 'Columns' })}
          data-testid="gantt-columns-menu"
          className="absolute end-0 top-full z-30 mt-1 w-48 rounded-lg border border-border-light bg-surface-primary py-1 shadow-lg"
        >
          {GANTT_COLUMNS.map((c) => {
            const checked = selected.includes(c.id);
            return (
              <label
                key={c.id}
                role="menuitemcheckbox"
                aria-checked={checked}
                className={`flex items-center gap-2 px-3 py-1.5 text-xs text-content-primary ${
                  c.required ? 'opacity-60' : 'cursor-pointer hover:bg-surface-secondary'
                }`}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={c.required}
                  onChange={() => toggleColumn(c.id)}
                  data-testid={`gantt-column-toggle-${c.id}`}
                />
                {t(c.labelKey, { defaultValue: c.defaultLabel })}
              </label>
            );
          })}
          <button
            type="button"
            onClick={() => reset()}
            className="mt-1 w-full border-t border-border-light px-3 py-1.5 text-start text-xs text-content-secondary hover:bg-surface-secondary"
          >
            {t('gantt.columns_reset', { defaultValue: 'Reset columns and widths' })}
          </button>
        </div>
      )}
    </div>
  );
}

export interface GanttTablePanelProps {
  activities: GanttActivity[];
  rowHeight: number;
  headerHeight: number;
  showCriticalPath: boolean;
  /** Width of the start and end columns until the reader drags them (wider with a year). */
  dateColWidth: number;
  formatDate: (iso: string) => string;
  onActivityClick?: (id: string) => void;
  bodyRef: Ref<HTMLDivElement>;
  onBodyScroll: UIEventHandler<HTMLDivElement>;
}

export function GanttTablePanel({
  activities,
  rowHeight,
  headerHeight,
  showCriticalPath,
  dateColWidth,
  formatDate,
  onActivityClick,
  bodyRef,
  onBodyScroll,
}: GanttTablePanelProps) {
  const { t } = useTranslation();
  const picked = useGanttTablePrefsStore((s) => s.columns);
  const widths = useGanttTablePrefsStore((s) => s.widths);
  const tableWidth = useGanttTablePrefsStore((s) => s.tableWidth);
  const setTableWidth = useGanttTablePrefsStore((s) => s.setTableWidth);
  const panelRef = useRef<HTMLDivElement>(null);

  const columns = visibleColumns(picked);
  const widthOf = useCallback(
    (c: GanttColumnDef): number =>
      widths[c.id] ?? (c.id === 'start' || c.id === 'end' ? dateColWidth : c.defaultWidth),
    [widths, dateColWidth],
  );
  const natural = columns.reduce((sum, c) => sum + widthOf(c), 0) + PICKER_WIDTH;
  const panelWidth = tableWidth ?? natural;

  const splitter = useEdgeResize(
    () => panelRef.current?.offsetWidth || panelWidth,
    (px) => setTableWidth(px),
    () => setTableWidth(null),
  );

  const header = (c: GanttColumnDef) => {
    const label = t(c.labelKey, { defaultValue: c.defaultLabel });
    return (
      <div
        key={c.id}
        className={`relative flex items-end px-2 pb-1.5 ${c.id === 'name' ? 'min-w-0 flex-1' : 'shrink-0'} ${
          c.align === 'end' ? 'justify-end' : ''
        }`}
        style={c.id === 'name' ? { minWidth: widthOf(c) } : { width: widthOf(c) }}
        data-testid={`gantt-col-head-${c.id}`}
      >
        <span className="truncate text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
          {c.id === 'progress' ? '%' : label}
        </span>
        <ColumnResizer
          def={c}
          label={t('gantt.resize_column', { defaultValue: 'Resize column {{name}}', name: label })}
          current={() => widthOf(c)}
        />
      </div>
    );
  };

  const cell = (c: GanttColumnDef, a: GanttActivity, isCritical: boolean) => {
    const base = `px-2 ${c.id === 'name' ? 'min-w-0 flex-1' : 'shrink-0'} ${c.align === 'end' ? 'text-end' : 'text-start'}`;
    const style = c.id === 'name' ? { minWidth: widthOf(c) } : { width: widthOf(c) };
    const testId = c.id === 'start' || c.id === 'end' ? `gantt-${c.id}-${a.id}` : `gantt-col-${c.id}-${a.id}`;
    switch (c.id) {
      case 'name':
        return (
          <div key={c.id} className={`${base} flex items-center gap-1.5 !px-3`} style={style}>
            {a.isMilestone && (
              <svg width="10" height="10" viewBox="0 0 10 10" className="shrink-0">
                <polygon points="5,0 10,5 5,10 0,5" fill={isCritical ? '#ef4444' : '#3b82f6'} />
              </svg>
            )}
            {a.isGroup && <span className="shrink-0 text-[10px] font-bold text-content-tertiary">[G]</span>}
            <span
              className={`truncate text-xs ${a.isGroup ? 'font-bold' : 'font-medium'} text-content-primary`}
              title={a.name}
            >
              {a.name}
            </span>
            {isCritical && (
              <span className="shrink-0 rounded bg-red-500 px-1 py-0.5 text-[8px] font-bold leading-none text-white">
                CP
              </span>
            )}
          </div>
        );
      case 'start':
      case 'end':
        return (
          <div key={c.id} className={base} data-testid={testId} style={style}>
            <span className="text-2xs tabular-nums text-content-tertiary">{formatDate(c.id === 'start' ? a.start : a.end)}</span>
          </div>
        );
      case 'progress':
        return (
          <div key={c.id} className={`${base} !px-1`} data-testid={testId} style={style}>
            <span
              className={`text-2xs font-medium tabular-nums ${
                a.progress >= 100 ? 'text-green-600' : a.progress > 0 ? 'text-blue-600' : 'text-content-tertiary'
              }`}
            >
              {a.progress}
            </span>
          </div>
        );
      default: {
        const text =
          c.id === 'wbs'
            ? (a.wbs ?? '')
            : c.id === 'duration'
              ? a.durationDays != null
                ? String(a.durationDays)
                : ''
              : c.id === 'predecessors'
                ? formatPredecessors(a.predecessors)
                : (a.resources ?? '');
        return (
          <div key={c.id} className={`${base} min-w-0`} data-testid={testId} style={style}>
            <span className="block truncate text-2xs tabular-nums text-content-secondary" title={text}>
              {text}
            </span>
          </div>
        );
      }
    }
  };

  return (
    <>
      <div
        ref={panelRef}
        className="flex flex-col overflow-x-auto"
        style={{ width: panelWidth }}
        data-testid="gantt-table"
      >
        <div className="flex min-h-0 flex-1 flex-col" style={{ minWidth: natural }}>
          <div
            className="flex shrink-0 border-b border-border-light bg-surface-secondary/60"
            style={{ height: headerHeight }}
          >
            {columns.map(header)}
            <ColumnPicker selected={picked} />
          </div>
          <div
            ref={bodyRef}
            className="flex-1 overflow-y-auto overflow-x-hidden"
            onScroll={onBodyScroll}
            style={{ scrollbarWidth: 'none' }}
          >
            {activities.map((a, idx) => {
              const isCritical = showCriticalPath && !!a.isCritical;
              return (
                <div
                  key={a.id}
                  className={`flex items-center border-b border-border-light/60 transition-colors hover:bg-surface-secondary/40 ${
                    idx % 2 === 0 ? 'bg-surface-primary' : 'bg-surface-secondary/20'
                  } ${isCritical ? 'bg-red-50 dark:bg-red-950/20' : ''} ${onActivityClick ? 'cursor-pointer' : ''}`}
                  style={{ height: rowHeight }}
                  onClick={() => onActivityClick?.(a.id)}
                >
                  {columns.map((c) => cell(c, a, isCritical))}
                  <div className="shrink-0" style={{ width: PICKER_WIDTH }} />
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={t('gantt.resize_table', { defaultValue: 'Resize the table' })}
        aria-valuenow={panelWidth}
        aria-valuemin={GANTT_TABLE_MIN_WIDTH}
        aria-valuemax={GANTT_TABLE_MAX_WIDTH}
        tabIndex={0}
        data-testid="gantt-splitter"
        className="w-1.5 shrink-0 cursor-col-resize touch-none border-e border-border-light bg-surface-secondary/40 hover:bg-oe-blue/30 focus-visible:bg-oe-blue/50 focus-visible:outline-none"
        {...splitter}
      />
    </>
  );
}
