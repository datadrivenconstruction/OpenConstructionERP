// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * UpcomingMilestonesCard - dashboard widget listing the next few upcoming
 * schedule milestones for the active project.
 *
 * These are the key dates a project manager cares about this week and soon.
 * Data flow:
 *   - `scheduleApi.listSchedules(projectId)` lists the project's schedules,
 *   - `scheduleApi.getGantt(scheduleId)` returns that schedule's activities.
 * A milestone is an activity whose `activity_type === 'milestone'`; its due
 * date is the activity `end_date`. We keep milestones that are not yet
 * complete (`progress_pct < 100`), sort ascending by date and take the next
 * five, including recently overdue ones so they are not missed.
 *
 * Self-hides (returns null) when there is no active project, while loading,
 * or when there are no upcoming milestones - the dashboard stays uncluttered
 * for projects without a schedule.
 */

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { CalendarClock, Flag, ArrowRight } from 'lucide-react';
import { Card, CardContent, CardHeader, InfoHint } from '@/shared/ui';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import { formatDateWithPreference } from '@/shared/lib/formatters';
import { scheduleApi, type Activity } from '@/features/schedule/api';

/** How many days before/after "today" a milestone stays worth showing. */
const MAX_UPCOMING = 5;
/** Keep recently overdue-but-open milestones within this window so they are not missed. */
const OVERDUE_GRACE_DAYS = 14;

interface UpcomingMilestone {
  id: string;
  name: string;
  dueDate: string;
  /** Whole days from today. Negative = overdue, 0 = today, positive = future. */
  daysFromToday: number;
}

/** UTC midnight of the given local date, so only the date part is compared. */
function startOfDayUtc(date: Date): number {
  return Date.UTC(date.getFullYear(), date.getMonth(), date.getDate());
}

/** Whole days between two ISO date strings, comparing date parts only. */
function daysBetween(fromIso: string, toIso: string): number | null {
  const from = new Date(fromIso);
  const to = new Date(toIso);
  if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) return null;
  const msPerDay = 24 * 60 * 60 * 1000;
  return Math.round((startOfDayUtc(to) - startOfDayUtc(from)) / msPerDay);
}

function isComplete(activity: Activity): boolean {
  return activity.progress_pct >= 100 || activity.status === 'completed';
}

export function UpcomingMilestonesCard() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const projectId = useProjectContextStore((s) => s.activeProjectId) ?? '';

  const schedulesQuery = useQuery({
    queryKey: ['schedule', 'schedules', projectId],
    queryFn: () => scheduleApi.listSchedules(projectId).then((page) => page.items),
    enabled: Boolean(projectId),
    staleTime: 60 * 1000,
  });

  const schedules = schedulesQuery.data ?? [];
  const primaryScheduleId = schedules.length > 0 ? schedules[0]!.id : '';

  const ganttQuery = useQuery({
    queryKey: ['schedule', 'gantt', primaryScheduleId],
    queryFn: () => scheduleApi.getGantt(primaryScheduleId),
    enabled: Boolean(primaryScheduleId),
    staleTime: 60 * 1000,
  });

  const datePref = usePreferencesStore((s) => s.dateFormat);
  const formatDueDate = useMemo(() => {
    const locale = i18n.language || undefined;
    const options: Intl.DateTimeFormatOptions = {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    };
    return (d: Date) => formatDateWithPreference(d, locale, options, datePref);
  }, [i18n.language, datePref]);

  const milestones = useMemo<UpcomingMilestone[]>(() => {
    const activities = ganttQuery.data?.activities ?? [];
    const nowIso = new Date().toISOString();
    const rows: UpcomingMilestone[] = [];
    for (const a of activities) {
      if (a.activity_type !== 'milestone') continue;
      if (isComplete(a)) continue;
      const dueDate = a.end_date;
      if (!dueDate) continue;
      const days = daysBetween(nowIso, dueDate);
      if (days === null) continue;
      // Drop long-overdue milestones; keep the recent ones so they are not missed.
      if (days < -OVERDUE_GRACE_DAYS) continue;
      rows.push({ id: a.id, name: a.name, dueDate, daysFromToday: days });
    }
    rows.sort((x, y) => x.daysFromToday - y.daysFromToday);
    return rows.slice(0, MAX_UPCOMING);
  }, [ganttQuery.data]);

  if (!projectId) return null;
  if (schedulesQuery.isLoading || ganttQuery.isLoading) return null;
  if (milestones.length === 0) return null;

  return (
    <Card className="h-full">
      <CardHeader
        title={
          <span className="inline-flex items-center gap-2">
            <CalendarClock size={18} className="text-oe-blue" strokeWidth={1.75} />
            {t('dashboard.milestones_title', { defaultValue: 'Upcoming milestones' })}
          </span>
        }
        subtitle={t('dashboard.milestones_subtitle', {
          defaultValue: 'The next key dates from your schedule',
        })}
        action={
          <button
            type="button"
            onClick={() => navigate('/schedule')}
            className="inline-flex items-center gap-1.5 text-xs text-oe-blue hover:underline"
          >
            {t('dashboard.milestones_open', { defaultValue: 'Open schedule' })}
            <ArrowRight size={11} />
          </button>
        }
      />
      <CardContent>
        <ul className="flex flex-col gap-2.5">
          {milestones.map((m) => (
            <li key={m.id} className="flex items-center gap-3">
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-amber-50 text-amber-600 dark:bg-amber-950/40">
                <Flag size={13} strokeWidth={1.75} />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-content-primary">{m.name}</p>
                <p className="text-xs text-content-tertiary">{formatDueDate(new Date(m.dueDate))}</p>
              </div>
              <DueChip days={m.daysFromToday} t={t} />
            </li>
          ))}
        </ul>
        <InfoHint
          className="mt-3"
          text={t('dashboard.milestones_help', {
            defaultValue:
              'These are schedule activities marked as milestones that are not yet complete, sorted by date with the soonest first. The chip shows how many days until the date, or how far a date has already slipped. A milestone that has just passed stays listed for two weeks so it is not missed.',
          })}
        />
      </CardContent>
    </Card>
  );
}

interface DueChipProps {
  days: number;
  t: ReturnType<typeof useTranslation>['t'];
}

/** Small "in N days" / "overdue by N days" chip, coloured by urgency. */
function DueChip({ days, t }: DueChipProps) {
  let label: string;
  let tone: string;

  if (days < 0) {
    const n = Math.abs(days);
    label = t('dashboard.milestones_overdue', {
      defaultValue: 'overdue by {{n}} days',
      defaultValue_one: 'overdue by {{n}} day',
      count: n,
      n,
    });
    tone = 'bg-rose-50 text-rose-600 dark:bg-rose-950/40';
  } else if (days === 0) {
    label = t('dashboard.milestones_today', { defaultValue: 'today' });
    tone = 'bg-amber-50 text-amber-600 dark:bg-amber-950/40';
  } else {
    label = t('dashboard.milestones_in_days', {
      defaultValue: 'in {{n}} days',
      defaultValue_one: 'in {{n}} day',
      count: days,
      n: days,
    });
    tone = days <= 3 ? 'bg-amber-50 text-amber-600 dark:bg-amber-950/40' : 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/40';
  }

  return (
    <span className={`shrink-0 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium ${tone}`}>
      {label}
    </span>
  );
}

export default UpcomingMilestonesCard;
