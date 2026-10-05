// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The top bar's way back to the course: "Academy · Task 2 of 5", linking to
// the course map, plus the week-goal pill from the mockup on wider screens.
//
//   off       renders nothing: a normal install gets the same top bar as before
//   none      renders nothing: no course, nothing to go back to
//   checking / loading / error
//             a plain "Academy" chip, so the bar does not jump when the course
//             arrives and a learner whose course failed to load can reach the
//             map's Retry
//   enrolled  the task chip (or "Course complete") and the week pill
//
// On a phone only the cap icon and "2/5" show; the full sentence stays the
// link's accessible name.

import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { GraduationCap } from 'lucide-react';

import { useI18nReady } from '@/shared/lib/useI18nReady';

import { isCourseFinished, nextTaskOf } from './CoursePath';
import { COURSE_MAP_ROUTE } from './routeMatch';
import { useTrainerMode } from './useTrainerMode';
import { weekGoal } from './WeekStrip';

const CHIP =
  'inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full bg-oe-purple-subtle px-3 text-[13px] font-semibold text-oe-purple-text ring-1 ring-inset ring-oe-purple/20 transition-colors hover:bg-oe-purple/15 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-purple';

export function TrainerHeaderChip() {
  useI18nReady();
  const { t } = useTranslation();
  const mode = useTrainerMode();

  if (mode.state === 'off' || mode.state === 'none') return null;

  const academy = t('trainer.page_title', { defaultValue: 'Academy' });

  if (mode.state !== 'enrolled' || !mode.me) {
    return (
      <Link to={COURSE_MAP_ROUTE} className={CHIP} data-testid="trainer-header-chip">
        <GraduationCap size={15} aria-hidden="true" />
        <span>{academy}</span>
      </Link>
    );
  }

  const { tasks, week } = mode.me;
  const total = tasks.length;
  const finished = isCourseFinished(tasks);
  const next = nextTaskOf(tasks);
  // With nothing open and the course not finished (all remaining locked), the
  // chip still counts the first unpassed task, so it never says "Task 0".
  const current = next ?? [...tasks].sort((a, b) => a.n - b.n).find((task) => task.status !== 'passed') ?? null;

  const label = finished
    ? t('trainer.header.course_done', { defaultValue: 'Academy · Course complete' })
    : current
      ? t('trainer.header.task_chip', { defaultValue: 'Academy · Task {{n}} of {{total}}', n: current.n, total })
      : academy;
  const short = finished
    ? academy
    : current
      ? t('trainer.rings.count', { defaultValue: '{{done}}/{{total}}', done: current.n, total })
      : academy;

  return (
    <div className="flex shrink-0 items-center gap-2">
      <Link to={COURSE_MAP_ROUTE} className={CHIP} aria-label={label} data-testid="trainer-header-chip">
        <GraduationCap size={15} aria-hidden="true" />
        <span className="hidden sm:inline" aria-hidden="true">
          {label}
        </span>
        <span className="font-mono tabular-nums sm:hidden" aria-hidden="true">
          {short}
        </span>
      </Link>
      {week && (
        <span
          data-testid="trainer-header-week"
          className="hidden h-8 items-center rounded-full bg-oe-blue-subtle px-3 text-[13px] font-semibold text-oe-blue-text lg:inline-flex"
        >
          {t('trainer.header.week_goal', {
            defaultValue: 'Week goal {{done}}/{{goal}}',
            done: Math.max(0, week.done),
            goal: weekGoal(week.goal),
          })}
        </span>
      )}
    </div>
  );
}
