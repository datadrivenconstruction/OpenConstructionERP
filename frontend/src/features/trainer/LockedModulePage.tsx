// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What a learner sees in place of a module (or a panel, through
// LockedPanelCard) that their course has not opened yet. Layout after
// Locked.dc.html: a lock tile, "Variations opens after task 3", one plain
// sentence naming the task that opens it, the path from task 1 to that task,
// a button straight to the task to do now, and a note that nothing is lost.
//
// Locks are UI only: the module's API stays open and nothing here blocks a
// request. The page title is not touched (App.tsx's `P` keeps setting it), so
// a locked /variations still reads "Variations" in the header.
//
// The course text (module label, task titles, reason) is written in the
// course language and sits in containers that carry its `lang` and `dir`;
// the chrome around it follows the UI language.

import { useId } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Check, Loader2, Lock } from 'lucide-react';

import { ErrorState } from '@/shared/ui/ErrorState';

import { courseDir, courseLocaleOf } from './courseLocale';
import { renderCourseText } from './courseText';
import { getLock } from './lockRegistry';
import { COURSE_MAP_ROUTE } from './routeMatch';
import type { TaskStatus, TaskSummary, TrainerMe } from './types';
import type { TrainerMode } from './useTrainerMode';
import { useTrainerUiStore } from './useTrainerUiStore';

// ── Pure helpers (exported for tests and for the panel card) ────────────────

function byNumber(a: TaskSummary, b: TaskSummary): number {
  return a.n - b.n;
}

/**
 * The task whose pass opens `lockId`: the one that names it in `opens`, else
 * the one the unlock row points at.
 */
export function openingTaskFor(me: Pick<TrainerMe, 'tasks' | 'unlocks'>, lockId: string): TaskSummary | null {
  const named = me.tasks.find((task) => task.opens === lockId);
  if (named) return named;
  const n = me.unlocks.find((u) => u.lock_id === lockId)?.opened_by_task;
  return n === undefined ? null : (me.tasks.find((task) => task.n === n) ?? null);
}

function isActionable(task: TaskSummary): boolean {
  return task.status !== 'passed' && task.status !== 'locked' && task.target !== null;
}

/**
 * The task the "Go to task" button opens on the way to task `upTo` (the one
 * that opens the lock): that task itself when the learner can work on it,
 * else the first earlier task that is neither passed nor locked and has
 * somewhere to go. Null when nothing can be opened, in which case no button
 * is drawn.
 */
export function nextActionTask(tasks: readonly TaskSummary[], upTo: number): TaskSummary | null {
  const path = tasks.filter((task) => task.n <= upTo).sort(byNumber);
  const opening = path.find((task) => task.n === upTo);
  if (opening && isActionable(opening)) return opening;
  return path.find(isActionable) ?? null;
}

/** Where a task's button goes: its route, plus `#anchor` when it names one. */
export function taskHref(task: Pick<TaskSummary, 'target'>): string | null {
  const target = task.target;
  if (!target) return null;
  if (!target.anchor || target.route.includes('#')) return target.route;
  return `${target.route}#${target.anchor}`;
}

// ── Shared pieces ───────────────────────────────────────────────────────────

const PILL_BASE =
  'inline-flex min-h-[44px] items-center justify-center rounded-full px-5 text-sm font-semibold transition-colors ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2';
export const PILL_PRIMARY = clsx(PILL_BASE, 'bg-oe-blue text-content-inverse hover:bg-oe-blue-hover');
export const PILL_SECONDARY = clsx(
  PILL_BASE,
  'border-[1.5px] border-border bg-transparent text-content-primary hover:bg-surface-secondary',
);

function LockedLoading() {
  const { t } = useTranslation();
  return (
    <div role="status" aria-live="polite" className="flex items-center justify-center py-10">
      <Loader2 size={22} className="animate-spin text-content-tertiary motion-reduce:animate-none" aria-hidden="true" />
      <span className="sr-only">{t('trainer.state.loading', { defaultValue: 'Loading your course' })}</span>
    </div>
  );
}

function CourseMapLink({ compact }: { compact: boolean }) {
  const { t } = useTranslation();
  return (
    <Link to={COURSE_MAP_ROUTE} className={clsx(PILL_SECONDARY, compact && 'min-h-[40px] px-4')}>
      {t('trainer.locked.course_map', { defaultValue: 'Course map' })}
    </Link>
  );
}

type PathMark = 'done' | 'current' | 'todo';

function PathCircle({ mark, n }: { mark: PathMark; n: number }) {
  return (
    <span
      aria-hidden="true"
      className={clsx(
        'inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border-[3px] text-sm font-bold',
        mark === 'done' && 'border-semantic-success-vivid bg-semantic-success-vivid text-white',
        mark === 'current' && 'border-oe-blue bg-oe-blue text-content-inverse',
        mark === 'todo' && 'border-border bg-surface-secondary text-content-secondary',
      )}
    >
      {mark === 'done' ? <Check size={16} strokeWidth={3} /> : n}
    </span>
  );
}

// ── The content, page or panel ─────────────────────────────────────────────

/**
 * The trainer state a locked screen draws from: the `useTrainerMode()` result
 * of the component that decided to show it.
 *
 * Passed down rather than read again on purpose. React Query v5 puts a query
 * with no data back to `pending` when it refetches, and a new observer of a
 * failed `/me` refetches on mount. A locked screen that observed `/me` itself
 * would mount only in the error state, refetch, flip the state to loading,
 * unmount, see the error again and mount again: a request loop.
 */
export type TrainerLockMode = Pick<TrainerMode, 'state' | 'me' | 'refetch'>;

export interface LockedLockContentProps {
  /** The closed lock. Null on the error outcome, where the lock is unknown. */
  lockId: string | null;
  variant: 'page' | 'panel';
  mode: TrainerLockMode;
}

/** The locked explanation itself, plus its loading and error states. */
export function LockedLockContent({ lockId, variant, mode }: LockedLockContentProps) {
  const { t } = useTranslation();
  const headingId = useId();
  const openTask = useTrainerUiStore((s) => s.openTask);
  const compact = variant === 'panel';
  const Heading = compact ? 'h2' : 'h1';

  if (mode.state === 'error') {
    return (
      <div className={clsx('flex w-full flex-col gap-3', compact ? '' : 'max-w-[640px]')}>
        <ErrorState
          title={t('trainer.state.error_title', { defaultValue: 'Your course did not load' })}
          hint={t('trainer.state.error_hint', { defaultValue: 'Nothing you entered is lost. Try again in a moment.' })}
          onRetry={mode.refetch}
        />
        <div className="flex justify-center">
          <CourseMapLink compact={compact} />
        </div>
      </div>
    );
  }
  if (mode.state === 'checking' || mode.state === 'loading') return <LockedLoading />;
  const me = mode.me;
  if (!me || !lockId) return null;
  // A badge or an id the registry does not know is never a locked screen.
  if (!getLock(lockId)) return null;

  const courseLocale = courseLocaleOf(me.course);
  const dir = courseDir(courseLocale);
  const opening = openingTaskFor(me, lockId);
  const openingN = opening?.n ?? me.unlocks.find((u) => u.lock_id === lockId)?.opened_by_task ?? null;
  const action = openingN === null ? null : nextActionTask(me.tasks, openingN);
  const actionHref = action ? taskHref(action) : null;
  const path = openingN === null ? [] : me.tasks.filter((task) => task.n <= openingN).sort(byNumber);
  const label = opening?.opens_label ?? '';

  // What a screen reader hears after "Task 2": the task's own status, not the
  // circle's colour.
  const statusText = (status: TaskStatus): string => {
    switch (status) {
      case 'passed':
        return t('trainer.status.passed', { defaultValue: 'Verified' });
      case 'in_progress':
        return t('trainer.status.in_progress', { defaultValue: 'In progress' });
      case 'needs_revision':
        return t('trainer.status.needs_revision', { defaultValue: 'Needs another look' });
      case 'not_started':
        return t('trainer.status.not_started', { defaultValue: 'Not started' });
      case 'locked':
        return t('trainer.status.locked', { defaultValue: 'Locked' });
    }
  };

  return (
    <section
      aria-labelledby={headingId}
      className={clsx(
        'flex w-full flex-col border border-border-light bg-surface-elevated',
        compact
          ? 'gap-4 rounded-xl p-4 shadow-xs sm:p-5'
          : 'max-w-[640px] items-center gap-[22px] rounded-3xl p-6 text-center shadow-sm sm:p-10',
      )}
    >
      <div className={clsx('flex gap-4', compact ? 'items-start' : 'flex-col items-center')}>
        <span
          aria-hidden="true"
          className={clsx(
            'inline-flex shrink-0 items-center justify-center bg-surface-secondary text-content-secondary',
            compact ? 'h-10 w-10 rounded-xl' : 'h-16 w-16 rounded-[20px]',
          )}
        >
          <Lock size={compact ? 18 : 30} strokeWidth={2} />
        </span>
        <div className="flex min-w-0 flex-col gap-2">
          <Heading
            id={headingId}
            className={clsx(
              'm-0 font-semibold tracking-tight text-content-primary',
              compact ? 'text-base' : 'text-2xl sm:text-[28px]',
            )}
          >
            {opening && openingN !== null
              ? t('trainer.locked.title', { defaultValue: '{{module}} opens after task {{n}}', module: label, n: openingN })
              : t('trainer.status.locked', { defaultValue: 'Locked' })}
          </Heading>
          {opening && (
            <p className={clsx('m-0 leading-relaxed text-content-secondary', compact ? 'text-sm' : 'text-base')}>
              {t('trainer.locked.body', {
                defaultValue: 'Finish task {{n}}, {{title}}, and this opens.',
                n: opening.n,
                title: renderCourseText(opening.title, courseLocale),
              })}
            </p>
          )}
          {opening?.lock_reason && (
            <p lang={courseLocale} dir={dir} className="m-0 text-sm leading-relaxed text-content-secondary">
              {renderCourseText(opening.lock_reason, courseLocale)}
            </p>
          )}
        </div>
      </div>

      {path.length > 0 && (
        <ol
          aria-label={t('trainer.locked.path_label', { defaultValue: 'Your path to this module' })}
          className={clsx('m-0 flex w-full list-none flex-wrap items-start p-0', compact ? 'gap-y-3' : 'max-w-[460px] gap-y-4')}
        >
          {path.map((task) => {
            const mark: PathMark = task.status === 'passed' ? 'done' : task.id === action?.id ? 'current' : 'todo';
            return (
              <li
                key={task.id}
                aria-current={mark === 'current' ? 'step' : undefined}
                className="flex min-w-[64px] flex-1 flex-col items-center gap-2"
              >
                <PathCircle mark={mark} n={task.n} />
                <span
                  className={clsx(
                    'text-xs leading-snug',
                    mark === 'current' ? 'font-bold text-content-primary' : 'font-medium',
                    mark === 'todo' ? 'text-content-tertiary' : 'text-content-primary',
                  )}
                >
                  {t('trainer.locked.path_task', { defaultValue: 'Task {{n}}', n: task.n })}
                  <span className="sr-only">, {statusText(task.status)}</span>
                </span>
              </li>
            );
          })}
          <li className="flex min-w-[64px] flex-1 flex-col items-center gap-2">
            <span
              aria-hidden="true"
              className="inline-flex h-9 w-9 items-center justify-center rounded-full border-[3px] border-border bg-surface-secondary text-content-tertiary"
            >
              <Lock size={14} strokeWidth={2.4} />
            </span>
            <span className="text-xs font-medium leading-snug text-content-tertiary">
              <span lang={courseLocale} dir={dir}>
                {label}
              </span>
              <span className="sr-only">, {statusText('locked')}</span>
            </span>
          </li>
        </ol>
      )}

      <div className={clsx('flex flex-wrap gap-2.5', compact ? '' : 'justify-center')}>
        {action && actionHref && (
          <Link
            to={actionHref}
            onClick={() => openTask(action.id)}
            className={clsx(PILL_PRIMARY, compact && 'min-h-[40px] px-4')}
          >
            {t('trainer.locked.go_to_task', { defaultValue: 'Go to task {{n}}', n: action.n })}
          </Link>
        )}
        <CourseMapLink compact={compact} />
      </div>

      <p className="m-0 text-xs text-content-tertiary">
        {t('trainer.locked.data_safe', {
          defaultValue: 'Your project and everything you entered stay as they are while a module is locked.',
        })}
      </p>
    </section>
  );
}

// ── The page ────────────────────────────────────────────────────────────────

export interface LockedModulePageProps {
  /** The closed lock, or null for the error outcome (the course did not load). */
  lockId: string | null;
  /** The caller's `useTrainerMode()` result; see `TrainerLockMode`. */
  mode: TrainerLockMode;
}

/** Full-page lock, rendered by `TrainerRouteOutcome` in place of a module. */
export function LockedModulePage({ lockId, mode }: LockedModulePageProps) {
  return (
    <div className="flex min-h-[60vh] w-full items-center justify-center px-4 py-10" data-testid="trainer-locked-page">
      <LockedLockContent lockId={lockId} variant="page" mode={mode} />
    </div>
  );
}
