// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "This week": verified tasks in the current ISO week against the course's
// weekly goal. The days come from the API (passed checks per ISO week,
// decision 4); this component counts nothing itself.
//
// No loss framing: there is no streak to break, an empty day is neutral grey
// (never red), and reaching the goal earns a quiet "goal reached" line. Rest
// passes are a v2 idea and are not shown.
//
// Day names are chrome, so they follow the UI language. Dates are pinned to
// UTC, the same way course dates are, so a day never shifts by one.

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Check } from 'lucide-react';

import { parseIsoDate } from './courseText';
import type { WeekDay } from './types';

/** The weekly goal when the course does not set one. */
export const DEFAULT_WEEK_GOAL = 3;

export interface WeekStripProps {
  /** Verified tasks the course asks for per week; anything below 1 means the default. */
  goal: number | null | undefined;
  /** Verified tasks this week. */
  done: number;
  /** Seven days from the API, Monday first. Empty: only the title and summary show. */
  days: WeekDay[];
  /** Today as YYYY-MM-DD, to mark it. Omit to mark nothing. */
  today?: string;
  className?: string;
}

export function weekGoal(goal: number | null | undefined): number {
  return typeof goal === 'number' && Number.isFinite(goal) && goal >= 1 ? Math.round(goal) : DEFAULT_WEEK_GOAL;
}

function formatter(locale: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  try {
    return new Intl.DateTimeFormat(locale, { ...options, timeZone: 'UTC' });
  } catch {
    return new Intl.DateTimeFormat('en', { ...options, timeZone: 'UTC' });
  }
}

export function WeekStrip({ goal, done, days, today, className }: WeekStripProps) {
  const { t, i18n } = useTranslation();
  const uiLocale = i18n.language || 'en';
  const shortDay = formatter(uiLocale, { weekday: 'short' });
  const longDay = formatter(uiLocale, { weekday: 'long', day: 'numeric', month: 'long' });
  const target = weekGoal(goal);
  const count = Math.max(0, done);

  const title = t('trainer.week.title', { defaultValue: 'This week' });
  const dayAria = (state: WeekDay['state'], day: string) => {
    switch (state) {
      case 'done':
        return t('trainer.week.day_done_aria', { defaultValue: '{{day}}: verified task', day });
      case 'off':
        return t('trainer.week.day_off_aria', { defaultValue: '{{day}}: day off', day });
      default:
        return t('trainer.week.day_empty_aria', { defaultValue: '{{day}}: nothing yet', day });
    }
  };

  return (
    <div className={clsx('flex flex-col gap-3.5', className)} data-testid="trainer-week">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-[15px] font-semibold text-content-primary">{title}</h2>
        <span className="text-sm text-content-secondary">
          {t('trainer.week.summary', { defaultValue: '{{done}} of {{goal}} verified tasks', done: count, goal: target })}
        </span>
      </div>
      {days.length > 0 && (
        <ol aria-label={title} className="grid grid-cols-7 gap-1.5 sm:gap-2">
          {days.map((d) => {
            const date = parseIsoDate(d.date);
            const label = date ? shortDay.format(date) : d.date;
            const spoken = date ? longDay.format(date) : d.date;
            const isToday = today !== undefined && d.date === today;
            return (
              <li
                key={d.date}
                data-state={d.state}
                data-today={isToday || undefined}
                className="flex min-w-0 flex-col items-center gap-1.5 text-xs text-content-tertiary"
              >
                <span
                  aria-hidden="true"
                  className={clsx(
                    'inline-flex h-8 w-8 items-center justify-center rounded-full font-bold sm:h-[34px] sm:w-[34px]',
                    d.state === 'done' && 'bg-oe-blue text-white',
                    d.state === 'off' && 'border border-dashed border-border-light bg-transparent text-content-quaternary',
                    d.state === 'empty' && 'bg-surface-secondary text-content-quaternary',
                    isToday && 'ring-2 ring-oe-blue/40 ring-offset-2 ring-offset-surface-elevated',
                  )}
                >
                  {d.state === 'done' ? <Check size={16} strokeWidth={3} /> : d.state === 'off' ? '–' : null}
                </span>
                <span aria-hidden="true" className={clsx('truncate', isToday && 'font-semibold text-content-primary')}>
                  {label}
                </span>
                <span className="sr-only">{dayAria(d.state, spoken)}</span>
              </li>
            );
          })}
        </ol>
      )}
      {count >= target && (
        <p className="text-xs font-medium text-semantic-success" data-testid="trainer-week-goal-met">
          {t('trainer.week.goal_met', { defaultValue: 'Week goal reached. Anything more is a bonus.' })}
        </p>
      )}
    </div>
  );
}
