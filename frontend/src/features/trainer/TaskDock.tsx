// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The Academy task dock (frontend design §4, TaskDock): the task panel docked
// on the inline-end edge, beside the AI dock, resizable; a 56px rail when
// collapsed or when the screen has no room; a bottom sheet on a phone.
//
// It never covers the form the learner works in: as a panel or a rail it
// writes `html[data-trainer-dock="push"]` and `--oe-trainer-dock-offset`, and
// the app shell pads itself by that offset (index.css, Wave 2), the same way
// the AI dock pushes the page. Geometry is in dockGeometry.ts; the dock width,
// the open flag and the sheet state live in useTrainerUiStore.
//
// It reads the AI dock's position (`--oe-ai-dock-widget-offset`) and the
// sidebar width from inline styles on <html> through a MutationObserver, and
// only re-renders when one of those numbers changed (its own writes to <html>
// fire the observer too).
//
// Hidden on the course map (`/academy`, the map is the full view), on routes
// that sit outside the app shell, without a current task, and whenever the
// learner is not inside a course (`useTrainerMode`, decision 33).

import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronUp, Map as MapIcon, PanelRightClose, X } from 'lucide-react';

import { isFloatingChatHiddenOn, readSidebarWidthPx } from '@/features/erp-chat/useFloatingChat';
import { useFocusTrap } from '@/shared/hooks/useFocusTrap';

import {
  TRAINER_PUSH_MIN_VIEWPORT,
  TRAINER_SHEET_BELOW,
  TRAINER_SHEET_PEEK,
  applyTrainerDockLayout,
  clearTrainerDockLayout,
  readInlinePx,
  resolveTrainerDockMode,
  trainerDockFits,
  trainerDockMaxWidth,
  trainerDockWidth,
  trainerWidthFromDrag,
  trainerWidthFromKey,
  type DockEnvironment,
  type TrainerDockMode,
} from './dockGeometry';
import { COURSE_MAP_ROUTE } from './routeMatch';
import { TaskPanel } from './TaskPanel';
import type { TaskRings } from './types';
import { DOCK_WIDTH_MIN } from './useTrainerUiStore';
import { useTrainerMode } from './useTrainerMode';
import { useTrainerUiStore } from './useTrainerUiStore';

import './trainer.css';

export const TRAINER_DOCK_ID = 'oe-trainer-dock';
const AI_WIDGET_OFFSET_VAR = '--oe-ai-dock-widget-offset';

/** Routes where the dock never shows. */
export function isTrainerDockHiddenOn(pathname: string): boolean {
  const path = pathname.toLowerCase();
  if (path === COURSE_MAP_ROUTE || path.startsWith(`${COURSE_MAP_ROUTE}/`)) return true;
  return isFloatingChatHiddenOn(path);
}

function readEnvironment(): DockEnvironment {
  if (typeof window === 'undefined') return { viewportWidth: 1440, sidebarWidth: 0, aiOffset: 0 };
  const root = document.documentElement;
  const viewportWidth = window.innerWidth;
  return {
    viewportWidth,
    // Below `lg` the sidebar is a drawer and takes no width from the page.
    sidebarWidth: viewportWidth >= TRAINER_PUSH_MIN_VIEWPORT ? readSidebarWidthPx(root) : 0,
    aiOffset: readInlinePx(root, AI_WIDGET_OFFSET_VAR),
  };
}

/** Viewport, docked sidebar and AI dock, updated only when one of them changes. */
export function useDockEnvironment(): DockEnvironment {
  const [env, setEnv] = useState<DockEnvironment>(readEnvironment);
  useEffect(() => {
    const update = () =>
      setEnv((prev) => {
        const next = readEnvironment();
        return prev.viewportWidth === next.viewportWidth &&
          prev.sidebarWidth === next.sidebarWidth &&
          prev.aiOffset === next.aiOffset
          ? prev
          : next;
      });
    update();
    window.addEventListener('resize', update);
    const observer = typeof MutationObserver === 'undefined' ? null : new MutationObserver(update);
    observer?.observe(document.documentElement, { attributes: true, attributeFilter: ['style', 'data-ai-dock'] });
    return () => {
      window.removeEventListener('resize', update);
      observer?.disconnect();
    };
  }, []);
  return env;
}

/** How many of the task's rings are closed, as a small ring for the rail and the peek. */
function MiniRing({ rings }: { rings: TaskRings | null }) {
  const done = rings ? [rings.numbers, rings.trace, rings.explain].filter(Boolean).length : 0;
  const r = 10;
  const c = 2 * Math.PI * r;
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true" className="shrink-0">
      <circle cx="14" cy="14" r={r} fill="none" stroke="currentColor" strokeOpacity="0.18" strokeWidth="4" />
      <circle
        cx="14"
        cy="14"
        r={r}
        fill="none"
        stroke="var(--oe-trainer-ring-numbers, #0071e3)"
        strokeWidth="4"
        strokeLinecap="round"
        strokeDasharray={`${(c * done) / 3} ${c}`}
        transform="rotate(-90 14 14)"
      />
    </svg>
  );
}

export interface TaskDockProps {
  /** Show this task instead of the store's `dockTaskId` (tests, previews). */
  taskId?: string | null;
}

export function TaskDock({ taskId: taskIdProp }: TaskDockProps = {}) {
  const { t, i18n } = useTranslation();
  const location = useLocation();
  const trainer = useTrainerMode();
  const storeTaskId = useTrainerUiStore((s) => s.dockTaskId);
  const dockOpen = useTrainerUiStore((s) => s.dockOpen);
  const dockWidth = useTrainerUiStore((s) => s.dockWidth);
  const sheetExpanded = useTrainerUiStore((s) => s.sheetExpanded);
  const collapseDock = useTrainerUiStore((s) => s.collapseDock);
  const expandDock = useTrainerUiStore((s) => s.expandDock);
  const setDockWidth = useTrainerUiStore((s) => s.setDockWidth);
  const resetDockWidth = useTrainerUiStore((s) => s.resetDockWidth);
  const setSheetExpanded = useTrainerUiStore((s) => s.setSheetExpanded);
  const env = useDockEnvironment();

  const taskId = taskIdProp ?? storeTaskId;
  const me = trainer.me;
  const hidden = !trainer.active || !me || !taskId || isTrainerDockHiddenOn(location.pathname);
  const fits = trainerDockFits(env);
  const mode: TrainerDockMode = resolveTrainerDockMode({ ...env, open: dockOpen });
  const maxWidth = trainerDockMaxWidth(env);
  const width = trainerDockWidth(dockWidth, maxWidth);
  // Read at the moment of a key or a drag: the page direction can change under a mounted dock.
  const isRtl = useCallback(
    () => document.documentElement.dir === 'rtl' || i18n.dir?.() === 'rtl',
    [i18n],
  );

  const summary = me && taskId ? (me.tasks.find((s) => s.id === taskId) ?? null) : null;
  const total = me?.tasks.length ?? 0;
  const n = summary?.n ?? 0;

  // Fold to the rail when the panel stops fitting (the AI dock opens, the
  // window narrows) or a new task opens on a screen without room. The learner
  // can still open it: it then pushes at the narrowest width.
  const fitRef = useRef<{ fits: boolean | null; taskId: string | null }>({ fits: null, taskId: null });
  useEffect(() => {
    if (hidden) return;
    const prev = fitRef.current;
    fitRef.current = { fits, taskId };
    const lostRoom = !fits && (prev.fits !== false || prev.taskId !== taskId);
    if (lostRoom && env.viewportWidth >= TRAINER_SHEET_BELOW && useTrainerUiStore.getState().dockOpen) collapseDock();
  }, [fits, taskId, hidden, env.viewportWidth, collapseDock]);

  // Tell the page where the dock is; take it all back when hidden or gone.
  useEffect(() => {
    const root = document.documentElement;
    if (hidden) clearTrainerDockLayout(root);
    else applyTrainerDockLayout(root, mode, width);
  }, [hidden, mode, width]);
  useEffect(() => () => clearTrainerDockLayout(document.documentElement), []);

  // A newly opened task takes focus to its heading ("Continue" on the map).
  const asideRef = useRef<HTMLElement>(null);
  const focusedTaskRef = useRef<string | null>(null);
  useEffect(() => {
    if (hidden || !taskId || focusedTaskRef.current === taskId) return;
    focusedTaskRef.current = taskId;
    if (mode !== 'push') return;
    const heading = document.getElementById('oe-trainer-task-heading');
    (heading ?? asideRef.current)?.focus();
  }, [hidden, taskId, mode]);

  // ── Resize (push only) ──────────────────────────────────────────────────
  const dragRef = useRef<{ startX: number; startWidth: number; pointerId: number } | null>(null);
  const [resizing, setResizing] = useState(false);
  const onPointerDown = useCallback(
    (e: PointerEvent<HTMLDivElement>) => {
      if (e.button !== 0) return;
      e.preventDefault();
      dragRef.current = { startX: e.clientX, startWidth: width, pointerId: e.pointerId };
      e.currentTarget.setPointerCapture?.(e.pointerId);
      setResizing(true);
    },
    [width],
  );
  const onPointerMove = useCallback(
    (e: PointerEvent<HTMLDivElement>) => {
      const drag = dragRef.current;
      if (!drag) return;
      setDockWidth(
        trainerWidthFromDrag({
          startWidth: drag.startWidth,
          startX: drag.startX,
          currentX: e.clientX,
          rtl: isRtl(),
          maxWidth,
        }),
      );
    },
    [isRtl, maxWidth, setDockWidth],
  );
  const onPointerEnd = useCallback(() => {
    dragRef.current = null;
    setResizing(false);
  }, []);
  const onResizeKey = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      const next = trainerWidthFromKey(e.key, { width, maxWidth, rtl: isRtl() });
      if (next === null) return;
      e.preventDefault();
      setDockWidth(next);
    },
    [width, maxWidth, isRtl, setDockWidth],
  );

  // ── Sheet: Esc collapses, focus stays inside, the page does not scroll ──
  const sheetRef = useRef<HTMLElement>(null);
  const sheetOpen = !hidden && mode === 'sheet' && sheetExpanded;
  useFocusTrap(sheetRef, sheetOpen);
  useEffect(() => {
    if (!sheetOpen) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        setSheetExpanded(false);
      }
    };
    document.addEventListener('keydown', onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [sheetOpen, setSheetExpanded]);

  if (hidden || !me || !taskId) return null;

  const regionLabel = t('trainer.panel.region_label', { defaultValue: 'Academy task' });
  const chip = t('trainer.header.task_chip', { defaultValue: 'Academy · Task {{n}} of {{total}}', n, total });
  const kicker = summary
    ? t('trainer.panel.kicker', { defaultValue: 'Task {{n}} · {{title}}', n, title: summary.title })
    : regionLabel;

  if (mode === 'sheet') {
    return (
      <>
        {sheetExpanded && (
          <div
            aria-hidden="true"
            className="oe-trainer-sheet-backdrop fixed inset-0 z-40 bg-black/30"
            onClick={() => setSheetExpanded(false)}
            data-testid="trainer-sheet-backdrop"
          />
        )}
        <section
          ref={sheetRef}
          id={TRAINER_DOCK_ID}
          role={sheetExpanded ? 'dialog' : 'region'}
          aria-modal={sheetExpanded ? true : undefined}
          aria-label={regionLabel}
          className="oe-trainer-sheet oe-trainer-dock-root fixed inset-x-0 bottom-0 z-40 flex flex-col rounded-t-2xl border-t border-border-light bg-surface-primary text-content-primary shadow-[0_-8px_24px_rgba(15,23,42,0.12)]"
          style={{ height: sheetExpanded ? '85vh' : `${TRAINER_SHEET_PEEK}px` }}
          data-testid="trainer-dock"
          data-mode="sheet"
          data-expanded={sheetExpanded || undefined}
        >
          <div className="flex h-16 shrink-0 items-center gap-2 px-3">
            <button
              type="button"
              aria-expanded={sheetExpanded}
              aria-controls={`${TRAINER_DOCK_ID}-body`}
              onClick={() => setSheetExpanded(!sheetExpanded)}
              className="flex min-h-[44px] min-w-0 flex-1 items-center gap-3 rounded-xl px-2 text-start focus-visible:outline focus-visible:outline-2 focus-visible:outline-oe-blue"
              data-testid="trainer-sheet-toggle"
            >
              <MiniRing rings={summary?.rings ?? null} />
              <span className="min-w-0 flex-1 truncate text-sm font-semibold">{kicker}</span>
              {sheetExpanded ? (
                <ChevronDown size={18} aria-hidden="true" />
              ) : (
                <ChevronUp size={18} aria-hidden="true" />
              )}
            </button>
            {sheetExpanded && (
              <button
                type="button"
                onClick={() => setSheetExpanded(false)}
                aria-label={t('trainer.panel.close_sheet', { defaultValue: 'Close task' })}
                className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-content-secondary hover:bg-surface-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-oe-blue"
              >
                <X size={18} aria-hidden="true" />
              </button>
            )}
          </div>
          {sheetExpanded && (
            <div id={`${TRAINER_DOCK_ID}-body`} className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
              <TaskPanel key={taskId} taskId={taskId} me={me} />
            </div>
          )}
        </section>
      </>
    );
  }

  if (mode === 'rail') {
    return (
      <aside
        ref={asideRef}
        id={TRAINER_DOCK_ID}
        aria-label={regionLabel}
        className="oe-trainer-dock oe-trainer-dock-root fixed inset-y-0 z-40 flex w-14 flex-col items-center border-s border-border-light bg-surface-primary text-content-primary shadow-[0_0_24px_rgba(15,23,42,0.08)]"
        data-testid="trainer-dock"
        data-mode="rail"
      >
        <button
          type="button"
          onClick={expandDock}
          aria-label={t('trainer.panel.expand', { defaultValue: 'Show task {{n}}', n })}
          title={t('trainer.panel.expand', { defaultValue: 'Show task {{n}}', n })}
          className="flex h-full w-full flex-col items-center gap-3 py-4 hover:bg-surface-secondary focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-oe-blue"
          data-testid="trainer-rail-expand"
        >
          <MiniRing rings={summary?.rings ?? null} />
          <span className="oe-trainer-rail-label text-xs font-semibold text-content-secondary">{chip}</span>
        </button>
      </aside>
    );
  }

  return (
    <aside
      ref={asideRef}
      id={TRAINER_DOCK_ID}
      aria-label={regionLabel}
      tabIndex={-1}
      className="oe-trainer-dock oe-trainer-dock-root fixed inset-y-0 z-40 flex flex-col border-s border-border-light bg-surface-secondary text-content-primary shadow-[0_0_24px_rgba(15,23,42,0.08)] focus:outline-none"
      style={{ width: `${width}px`, maxWidth: '100vw' }}
      data-testid="trainer-dock"
      data-mode="push"
      data-resizing={resizing || undefined}
    >
      <div
        role="separator"
        aria-orientation="vertical"
        aria-valuenow={width}
        aria-valuemin={DOCK_WIDTH_MIN}
        aria-valuemax={maxWidth}
        aria-controls={TRAINER_DOCK_ID}
        aria-label={t('trainer.panel.resize', { defaultValue: 'Resize task panel' })}
        tabIndex={0}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerEnd}
        onPointerCancel={onPointerEnd}
        onLostPointerCapture={onPointerEnd}
        onDoubleClick={resetDockWidth}
        onKeyDown={onResizeKey}
        className="group absolute inset-y-0 start-0 z-10 w-[6px] cursor-col-resize touch-none select-none focus-visible:outline-none"
        data-testid="trainer-dock-resize"
      >
        <span
          aria-hidden="true"
          className={`pointer-events-none absolute inset-y-0 start-0 w-[2px] bg-oe-blue transition-opacity group-hover:opacity-50 group-focus-visible:opacity-100 ${resizing ? 'opacity-100' : 'opacity-0'}`}
        />
      </div>
      <div className="flex h-14 shrink-0 items-center gap-2 border-b border-border-light bg-surface-primary px-4">
        {/* The task chip lives in the app header (stream A); this bar only names the region. */}
        <span className="min-w-0 flex-1 truncate text-xs font-bold uppercase tracking-wider text-content-secondary">
          {regionLabel}
        </span>
        <Link
          to={COURSE_MAP_ROUTE}
          className="inline-flex h-11 items-center gap-1.5 rounded-full px-3 text-xs font-semibold text-content-secondary hover:bg-surface-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-oe-blue"
        >
          <MapIcon size={15} aria-hidden="true" />
          {t('trainer.nav.course_map', { defaultValue: 'Course map' })}
        </Link>
        <button
          type="button"
          onClick={collapseDock}
          aria-label={t('trainer.panel.collapse', { defaultValue: 'Collapse task panel' })}
          title={t('trainer.panel.collapse', { defaultValue: 'Collapse task panel' })}
          className="inline-flex h-11 w-11 items-center justify-center rounded-full text-content-secondary hover:bg-surface-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-oe-blue"
          data-testid="trainer-dock-collapse"
        >
          <PanelRightClose size={18} className="rtl:-scale-x-100" aria-hidden="true" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        <TaskPanel key={taskId} taskId={taskId} me={me} />
      </div>
    </aside>
  );
}
