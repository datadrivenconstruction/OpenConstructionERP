// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The selected station's detail on the course map: what the task asks, where
// in the app it happens, what the check reads, the video, and what passing it
// opens. One button does the obvious next thing for the task's state:
//
//   not started        Start task N          -> dock + the task's screen
//   in progress        Continue in <screen>  -> same
//   needs another look Continue in <screen>  -> same
//   verified           Open task             -> same, to review it
//   locked             Go to task M          -> the task to work on now
//
// A locked task never sends the learner to itself: "Go to task M" names the
// task that is open now, and the line above it says which task opens this one.

import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { ArrowRight, Lock, PlayCircle } from 'lucide-react';

import { Button } from '@/shared/ui/Button';

import { courseDir } from './courseLocale';
import { renderCourseText } from './courseText';
import { stationStateOf, taskHref, useOpenTask, useTaskScreen, type StationState } from './CoursePath';
import { isBadgeLockId } from './lockRegistry';
import type { TaskSummary } from './types';

export interface TaskDetailProps {
  task: TaskSummary;
  /** The task to work on now, for a locked task's "Go to task" button. */
  nextTask: TaskSummary | null;
  courseLocale: string;
  /** DOM id the path stations point at with `aria-controls`. */
  id?: string;
}

const PILL: Record<StationState, string> = {
  done: 'bg-semantic-success-bg text-semantic-success',
  current: 'bg-oe-blue-subtle text-oe-blue-text',
  open: 'bg-oe-blue-subtle text-oe-blue-text',
  revision: 'bg-amber-50 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300',
  locked: 'bg-surface-secondary text-content-secondary',
};

export function TaskDetail({ task, nextTask, courseLocale, id }: TaskDetailProps) {
  const { t } = useTranslation();
  const screenOf = useTaskScreen();
  const openTask = useOpenTask();

  const state = stationStateOf(task);
  const screen = screenOf(task);
  const dir = courseDir(courseLocale);
  const text = (value: string | null) => (value ? renderCourseText(value, courseLocale) : '');

  const statusLabel: Record<TaskSummary['status'], string> = {
    not_started: t('trainer.status.not_started', { defaultValue: 'Not started' }),
    in_progress: t('trainer.status.in_progress', { defaultValue: 'In progress' }),
    needs_revision: t('trainer.status.needs_revision', { defaultValue: 'Needs another look' }),
    passed: t('trainer.status.passed', { defaultValue: 'Verified' }),
    locked: t('trainer.status.locked', { defaultValue: 'Locked' }),
  };

  // The one action, or none when there is nowhere to go.
  let action: { label: string; run: () => void } | null = null;
  if (state === 'locked') {
    if (nextTask && nextTask.id !== task.id && taskHref(nextTask, screenOf(nextTask))) {
      action = {
        label: t('trainer.locked.go_to_task', { defaultValue: 'Go to task {{n}}', n: nextTask.n }),
        run: () => void openTask(nextTask),
      };
    }
  } else if (taskHref(task, screen)) {
    const label =
      state === 'done'
        ? t('trainer.detail.open_task', { defaultValue: 'Open task' })
        : state === 'open'
          ? t('trainer.next.start', { defaultValue: 'Start task {{n}}', n: task.n })
          : t('trainer.next.continue', { defaultValue: 'Continue in {{module}}', module: screen.label });
    action = { label, run: () => void openTask(task) };
  }

  const badge = isBadgeLockId(task.opens);

  return (
    <div
      id={id}
      data-testid="trainer-task-detail"
      className="grid grid-cols-1 gap-6 border-t border-border-light pt-5 md:grid-cols-2"
    >
      <div className="flex min-w-0 flex-col gap-2">
        <div className="text-xs font-bold uppercase tracking-[0.06em] text-content-tertiary">
          {t('trainer.detail.task_kicker', { defaultValue: 'Task {{n}} · {{module}}', n: task.n, module: screen.label })}
        </div>
        <h3 lang={courseLocale} dir={dir} className="text-[22px] font-bold leading-tight text-content-primary">
          {text(task.title)}
        </h3>
        <span className={clsx('w-fit rounded-full px-2.5 py-0.5 text-xs font-semibold', PILL[state])}>
          {statusLabel[task.status]}
        </span>
        {state === 'locked' && (
          <p className="flex items-start gap-2 text-sm leading-relaxed text-content-secondary">
            <Lock size={15} className="mt-0.5 shrink-0" aria-hidden="true" />
            <span>
              {task.n > 1
                ? t('trainer.detail.locked_note', {
                    defaultValue: 'This task opens after task {{n}}.',
                    n: task.n - 1,
                  })
                : t('trainer.status.locked', { defaultValue: 'Locked' })}
              {task.lock_reason && (
                <>
                  {' '}
                  <span lang={courseLocale} dir={dir}>
                    {text(task.lock_reason)}
                  </span>
                </>
              )}
            </span>
          </p>
        )}
        {action && (
          <Button
            variant="primary"
            className="mt-2 w-fit min-h-[44px] rounded-full"
            icon={<ArrowRight size={16} />}
            iconPosition="right"
            onClick={action.run}
            data-testid="trainer-detail-action"
          >
            {action.label}
          </Button>
        )}
      </div>

      <dl className="grid grid-cols-[minmax(92px,auto)_1fr] gap-x-3 gap-y-2.5 text-sm">
        {task.checked_prompt && (
          <>
            <dt className="font-semibold text-content-primary">
              {t('trainer.detail.checked', { defaultValue: 'Checked' })}
            </dt>
            <dd lang={courseLocale} dir={dir} className="text-content-secondary">
              {text(task.checked_prompt)}
            </dd>
          </>
        )}
        <dt className="font-semibold text-content-primary">{t('trainer.detail.where', { defaultValue: 'Where' })}</dt>
        <dd className="text-content-secondary">{screen.label}</dd>
        {task.estimated_minutes !== null && task.estimated_minutes > 0 && (
          <>
            <dt className="font-semibold text-content-primary">
              {t('trainer.detail.time_label', { defaultValue: 'Time' })}
            </dt>
            <dd className="text-content-secondary">
              {t('trainer.detail.time', { defaultValue: 'About {{minutes}} min', minutes: task.estimated_minutes })}
            </dd>
          </>
        )}
        {task.video && (
          <>
            <dt className="font-semibold text-content-primary">
              {t('trainer.detail.watch', { defaultValue: 'Watch' })}
            </dt>
            <dd>
              <Link
                to={task.video.route}
                lang={courseLocale}
                className="inline-flex items-center gap-1.5 font-medium text-oe-blue-text hover:underline"
              >
                <PlayCircle size={15} aria-hidden="true" />
                {task.video.title}
              </Link>
            </dd>
          </>
        )}
        <dt className="font-semibold text-content-primary">
          {badge ? t('trainer.detail.earns', { defaultValue: 'Earns' }) : t('trainer.detail.opens', { defaultValue: 'Opens' })}
        </dt>
        <dd lang={courseLocale} dir={dir} className="text-content-secondary">
          {task.opens_label}
        </dd>
      </dl>
    </div>
  );
}
