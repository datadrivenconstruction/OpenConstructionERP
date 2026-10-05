// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The path on the course map: one station per task, in course order. Each
// station is a button that selects the task for the detail panel below it; a
// locked station selects too, so the learner can read what opens it.
//
// Every station says three things in plain words: what the learner does (the
// task title, course language), which screen of the app it happens in (the
// app's own name for that screen, UI language) and what passing it opens.
//
// One DOM list, two layouts: a vertical list of rows on a phone, a horizontal
// track of stations from `md` up, as in the mockup.
//
// The helpers below are shared with TaskDetail and CourseMapPage: which task
// is next, whether the course is finished, the screen a task happens in and
// the "open this task" action.

import { useCallback, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Check, Lock } from 'lucide-react';

import { courseDir } from './courseLocale';
import { renderCourseText } from './courseText';
import { isBadgeLockId } from './lockRegistry';
import { normalizePath, stripProjectPrefix } from './routeMatch';
import type { TaskSummary } from './types';
import { useTrainerUiStore } from './useTrainerUiStore';

// ── Pure helpers ────────────────────────────────────────────────────────────

/** Tasks in course order. */
export function sortTasks(tasks: readonly TaskSummary[]): TaskSummary[] {
  return [...tasks].sort((a, b) => a.n - b.n);
}

/**
 * The task to work on now: the first, in course order, that is neither passed
 * nor locked. Null when the course is finished, or when nothing is open.
 */
export function nextTaskOf(tasks: readonly TaskSummary[]): TaskSummary | null {
  return sortTasks(tasks).find((t) => t.status !== 'passed' && t.status !== 'locked') ?? null;
}

/** Every task passed. An empty task list is a broken course, never a finished one. */
export function isCourseFinished(tasks: readonly TaskSummary[]): boolean {
  return tasks.length > 0 && tasks.every((t) => t.status === 'passed');
}

export type StationState = 'done' | 'current' | 'open' | 'revision' | 'locked';

export function stationStateOf(task: TaskSummary): StationState {
  switch (task.status) {
    case 'passed':
      return 'done';
    case 'locked':
      return 'locked';
    case 'needs_revision':
      return 'revision';
    case 'in_progress':
      return 'current';
    default:
      return 'open';
  }
}

/** Passed tasks counted from the start of the path, for the green part of the track. */
export function passedRun(tasks: readonly TaskSummary[]): number {
  let run = 0;
  for (const task of sortTasks(tasks)) {
    if (task.status !== 'passed') break;
    run += 1;
  }
  return run;
}

// ── Screens ─────────────────────────────────────────────────────────────────

export interface TaskScreen {
  /** The app's own name for the screen, in the UI language. */
  label: string;
  /** The screen's base route, used when a task has no target route. */
  route: string | null;
}

// Route segment -> module id, for a task whose module id is unknown but whose
// target route is not.
const SEGMENT_MODULE: Record<string, string> = {
  boq: 'boq',
  'bid-management': 'bid_management',
  contracts: 'contracts',
  variations: 'variations',
  projects: 'projects',
  tendering: 'tendering',
  finance: 'finance',
  changeorders: 'changeorders',
};

function moduleFromRoute(route: string | null | undefined): string | null {
  if (!route) return null;
  const path = stripProjectPrefix(normalizePath(route));
  const segment = path.split('/').filter(Boolean)[0] ?? '';
  return SEGMENT_MODULE[segment] ?? (path.startsWith('/projects') ? 'projects' : null);
}

/**
 * Resolves the screen a task happens in. Every name is a literal key the app
 * already uses for that screen in its menu, so a learner reads the same word
 * here as in the sidebar.
 */
export function useTaskScreen(): (task: Pick<TaskSummary, 'module' | 'target'>) => TaskScreen {
  const { t } = useTranslation();
  return useCallback(
    (task) => {
      const screens: Record<string, TaskScreen> = {
        boq: { label: t('boq.title', { defaultValue: 'Bill of Quantities' }), route: '/boq' },
        bid_management: {
          label: t('nav.bid_management', { defaultValue: 'Bid Management' }),
          route: '/bid-management',
        },
        contracts: { label: t('nav.contracts', { defaultValue: 'Contracts' }), route: '/contracts' },
        variations: { label: t('nav.variations', { defaultValue: 'Variations' }), route: '/variations' },
        projects: { label: t('projects.title', { defaultValue: 'Projects' }), route: '/projects' },
        tendering: { label: t('tendering.title', { defaultValue: 'Tendering' }), route: '/tendering' },
        finance: { label: t('finance.title', { defaultValue: 'Finance' }), route: '/finance' },
        changeorders: { label: t('nav.change_orders', { defaultValue: 'Change Orders' }), route: '/changeorders' },
      };
      const id = (task.module || '').replace(/^oe_/, '');
      const known = screens[id] ?? screens[moduleFromRoute(task.target?.route) ?? ''];
      return known ?? { label: t('trainer.path.screen_other', { defaultValue: 'Another screen of the app' }), route: null };
    },
    [t],
  );
}

/**
 * Where "Start" / "Continue" goes: the task's target route plus its anchor,
 * else the screen's base route. Null when there is nowhere to go.
 */
export function taskHref(task: Pick<TaskSummary, 'target'>, screen: TaskScreen | null): string | null {
  const route = task.target?.route;
  if (route) {
    const anchor = task.target?.anchor;
    return anchor && !route.includes('#') ? `${route}#${anchor}` : route;
  }
  return screen?.route ?? null;
}

/**
 * The "open this task" action: show the task in the dock and go to the
 * screen it happens in. Returns false when the task has nowhere to go.
 */
export function useOpenTask(): (task: TaskSummary) => boolean {
  const navigate = useNavigate();
  const openTask = useTrainerUiStore((s) => s.openTask);
  const screenOf = useTaskScreen();
  return useCallback(
    (task) => {
      const href = taskHref(task, screenOf(task));
      if (!href || task.status === 'locked') return false;
      openTask(task.id);
      navigate(href);
      return true;
    },
    [navigate, openTask, screenOf],
  );
}

// ── Component ───────────────────────────────────────────────────────────────

export interface CoursePathProps {
  tasks: TaskSummary[];
  /** The task to work on now; its station pulses. */
  nextTaskId: string | null;
  /** The station whose detail shows below. */
  selectedTaskId: string | null;
  onSelect: (taskId: string) => void;
  courseLocale: string;
  /** Id of the detail panel the stations control. */
  detailId?: string;
  /** The selected task's detail, drawn under the stations inside the same card. */
  children?: ReactNode;
}

const DOT: Record<StationState, string> = {
  done: 'border-semantic-success bg-semantic-success text-white',
  current: 'border-oe-blue bg-oe-blue text-white',
  open: 'border-oe-blue bg-surface-elevated text-oe-blue-text',
  revision: 'border-amber-500 bg-amber-50 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300',
  locked: 'border-border bg-surface-secondary text-content-tertiary',
};

const CHIP: Record<StationState, string> = {
  done: 'bg-semantic-success-bg text-semantic-success',
  current: 'bg-oe-blue-subtle text-oe-blue-text',
  open: 'bg-oe-blue-subtle text-oe-blue-text',
  revision: 'bg-amber-50 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300',
  locked: 'bg-surface-secondary text-content-secondary',
};

export function CoursePath({
  tasks,
  nextTaskId,
  selectedTaskId,
  onSelect,
  courseLocale,
  detailId,
  children,
}: CoursePathProps) {
  const { t } = useTranslation();
  const screenOf = useTaskScreen();
  const ordered = sortTasks(tasks);
  const n = Math.max(1, ordered.length);
  const run = passedRun(ordered);
  // Station centres sit at (i + 0.5) / n of the width; the track joins the first to the last.
  const trackStart = 50 / n;
  const trackSpan = ((n - 1) * 100) / n;
  const trackFill = (Math.min(run, n - 1) * 100) / n;
  const dir = courseDir(courseLocale);

  const stationAria = (task: TaskSummary, state: StationState, title: string) => {
    const vars = { n: task.n, title };
    switch (state) {
      case 'done':
        return t('trainer.path.station_done', { defaultValue: 'Task {{n}}: {{title}}, verified', ...vars });
      case 'current':
        return t('trainer.path.station_current', { defaultValue: 'Task {{n}}: {{title}}, in progress', ...vars });
      case 'revision':
        return t('trainer.path.station_revision', { defaultValue: 'Task {{n}}: {{title}}, needs another look', ...vars });
      case 'locked':
        return t('trainer.path.station_locked', { defaultValue: 'Task {{n}}: {{title}}, locked', ...vars });
      default:
        return t('trainer.path.station_open', { defaultValue: 'Task {{n}}: {{title}}, ready to start', ...vars });
    }
  };

  // Arrow keys walk the stations (mirrored in a right-to-left UI), Home/End jump.
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const rtl = document.documentElement.dir === 'rtl';
    const forward = rtl ? 'ArrowLeft' : 'ArrowRight';
    const back = rtl ? 'ArrowRight' : 'ArrowLeft';
    let target = -1;
    if (event.key === forward || event.key === 'ArrowDown') target = Math.min(ordered.length - 1, index + 1);
    else if (event.key === back || event.key === 'ArrowUp') target = Math.max(0, index - 1);
    else if (event.key === 'Home') target = 0;
    else if (event.key === 'End') target = ordered.length - 1;
    if (target < 0 || target === index) return;
    event.preventDefault();
    const list = event.currentTarget.closest('[data-trainer-path]');
    list?.querySelectorAll<HTMLButtonElement>('[data-station]')[target]?.focus();
  };

  return (
    <section
      aria-labelledby="trainer-path-title"
      className="flex flex-col gap-6 rounded-[18px] bg-surface-elevated p-4 shadow-xs sm:px-6 sm:pb-6 sm:pt-7 lg:px-8"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="trainer-path-title" className="text-[17px] font-semibold text-content-primary">
          {t('trainer.path.title', { defaultValue: 'The path' })}
        </h2>
        <span className="text-[13px] text-content-secondary">
          {t('trainer.path.subtitle', { defaultValue: 'Every station is a checked result, not a video' })}
        </span>
      </div>

      <div className="md:overflow-x-auto">
        <div
          className="relative md:min-w-[calc(var(--trainer-stations)*136px)] md:pt-1"
          style={{ '--trainer-stations': n } as CSSProperties}
        >
          {/* Horizontal track, md and up. */}
          <div
            aria-hidden="true"
            className="absolute top-[30px] hidden h-1 rounded bg-border-light md:block"
            style={{ insetInlineStart: `${trackStart}%`, width: `${trackSpan}%` }}
          />
          <div
            aria-hidden="true"
            data-testid="trainer-path-track-fill"
            className="absolute top-[30px] hidden h-1 rounded bg-semantic-success md:block motion-safe:transition-[width] motion-safe:duration-700"
            style={{ insetInlineStart: `${trackStart}%`, width: `${trackFill}%` }}
          />
          {/* Vertical track, phone. */}
          <div
            aria-hidden="true"
            className="absolute bottom-8 top-8 w-1 rounded bg-border-light md:hidden"
            style={{ insetInlineStart: '30px' }}
          />

          <ol
            data-trainer-path=""
            className="relative flex flex-col gap-2 md:grid md:gap-2 md:[grid-template-columns:repeat(var(--trainer-stations),minmax(0,1fr))]"
          >
            {ordered.map((task, index) => {
              const state = stationStateOf(task);
              const title = renderCourseText(task.title, courseLocale);
              const pressed = task.id === selectedTaskId;
              const isNext = task.id === nextTaskId;
              const screen = screenOf(task);
              const badge = isBadgeLockId(task.opens);
              const opensText = badge
                ? t('trainer.path.earns', { defaultValue: 'Earns {{badge}}', badge: task.opens_label })
                : t('trainer.path.opens', { defaultValue: 'Opens {{module}}', module: task.opens_label });
              return (
                <li key={task.id} className="min-w-0">
                  <button
                    type="button"
                    data-station=""
                    data-state={state}
                    aria-pressed={pressed}
                    aria-controls={detailId}
                    aria-label={stationAria(task, state, title)}
                    aria-describedby={`${task.id}-where ${task.id}-opens`}
                    onClick={() => onSelect(task.id)}
                    onKeyDown={(e) => onKeyDown(e, index)}
                    className={clsx(
                      'group flex w-full min-w-[44px] items-start gap-3 rounded-[14px] p-1.5 text-start transition-colors',
                      'md:flex-col md:items-center md:gap-2.5 md:text-center',
                      'hover:bg-surface-secondary/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2 focus-visible:ring-offset-surface-elevated',
                      pressed && 'bg-surface-secondary/70 md:bg-transparent',
                    )}
                  >
                    <span className="relative inline-flex shrink-0">
                      {isNext && (
                        <span
                          aria-hidden="true"
                          data-testid="trainer-station-pulse"
                          className="absolute inset-0 rounded-full bg-oe-blue/35 motion-safe:animate-ping motion-reduce:hidden"
                        />
                      )}
                      <span
                        aria-hidden="true"
                        className={clsx(
                          'relative inline-flex h-[52px] w-[52px] items-center justify-center rounded-full border-[3px] font-bold',
                          DOT[state],
                        )}
                      >
                        {state === 'done' ? (
                          <Check size={22} strokeWidth={3} />
                        ) : state === 'locked' ? (
                          <Lock size={20} strokeWidth={2} />
                        ) : (
                          <span className="font-mono text-lg tabular-nums">{task.n}</span>
                        )}
                      </span>
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col gap-1 md:items-center" aria-hidden="true">
                      <span
                        lang={courseLocale}
                        dir={dir}
                        className={clsx(
                          'text-sm font-bold leading-snug',
                          state === 'locked' ? 'text-content-secondary' : 'text-content-primary',
                        )}
                      >
                        {title}
                      </span>
                      <span id={`${task.id}-where`} className="text-xs text-content-tertiary">
                        {screen.label}
                      </span>
                      <span
                        id={`${task.id}-opens`}
                        className={clsx(
                          'mt-0.5 inline-flex w-fit rounded-full px-2.5 py-1 text-xs font-semibold',
                          CHIP[state],
                        )}
                      >
                        {opensText}
                      </span>
                      <span
                        className={clsx(
                          'mt-1 hidden h-[3px] w-10 rounded md:block',
                          pressed ? 'bg-content-primary' : 'bg-transparent',
                        )}
                      />
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </div>
      </div>

      {children}
    </section>
  );
}
