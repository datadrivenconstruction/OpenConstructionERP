// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { listCalendars } from '@/features/schedule-advanced/api';
import { apiGet } from '@/shared/lib/api';
import type { HolidayCoverage, Schedule, WorkCalendarResponse } from './api';

const answered = new Set(['declared', 'project', 'platform']);

function object(value: unknown): Record<string, unknown> | undefined {
  return value != null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : undefined;
}

function coverage(value: unknown): HolidayCoverage | undefined {
  const row = object(value);
  return row && Number.isInteger(row.year) ? row as unknown as HolidayCoverage : undefined;
}

/** Read stored coverage rather than replacing an old plan's evidence with today's region. */
export function calendarCoverageProblems(schedule: Schedule, regional?: HolidayCoverage) {
  const own = object(schedule.metadata_?.calendar);
  const generated = own && 'regional_holiday_country' in own;
  const rows = generated
    ? (Array.isArray(own.holiday_coverage) ? own.holiday_coverage : []).map(coverage).filter((row): row is HolidayCoverage => !!row)
    : regional ? [regional] : [];
  const years = new Set(rows.map(row => row.year));
  if (generated) {
    const start = Number(schedule.start_date?.slice(0, 4));
    const end = Number(schedule.end_date?.slice(0, 4));
    if (Number.isInteger(start) && start > 0 && start <= 9999 && Number.isInteger(end) && end >= start && end <= 9999) {
      for (let year = start; year <= end; year++) years.add(year);
    }
  }
  const missing: number[] = [];
  const partial: number[] = [];
  for (const year of [...years].sort((a, b) => a - b)) {
    const row = rows.find(item => item.year === year);
    if (!row?.applied || !answered.has(row.jurisdiction?.source ?? '')) missing.push(year);
    else if (!answered.has(row.effective_year?.source ?? '') || !answered.has(row.holiday_extent?.source ?? '')
      || row.omitted?.length || row.placeholder_spans?.length) partial.push(year);
  }
  return { missing, partial };
}

export function CalendarCoverageNotice({ schedule }: { schedule: Schedule }) {
  const { t } = useTranslation();
  const own = object(schedule.metadata_?.calendar);
  const hasOwn = Array.isArray(own?.work_days) && own.work_days.length > 0;
  const manual = hasOwn && own !== undefined && !('regional_holiday_country' in own);
  const named = useQuery({
    queryKey: ['schedule-calendars', schedule.project_id],
    queryFn: () => listCalendars(schedule.project_id),
    enabled: !hasOwn,
  });
  const projectDefault = !hasOwn && named.data?.some(row => row.is_default);
  const region = useQuery({
    queryKey: ['work-calendar', schedule.project_id],
    queryFn: () => apiGet<WorkCalendarResponse>(`/v1/schedule/work-calendar/?project_id=${encodeURIComponent(schedule.project_id)}`),
    enabled: !hasOwn && named.isSuccess && !projectDefault,
    staleTime: 300_000,
  });
  const invalidRegion = region.isSuccess && (!Number.isFinite(region.data?.hours_per_day)
    || !Number.isFinite(region.data?.work_days_per_week) || !coverage(region.data?.holiday_coverage));
  if (manual || projectDefault) return null;
  if ((!hasOwn && named.isError) || (!hasOwn && (region.isError || invalidRegion))) {
    return <div role="alert" className="text-sm text-semantic-warning">
      {t('common.error', { defaultValue: 'Error' })}{' '}
      <button type="button" onClick={() => { void (named.isError ? named.refetch() : region.refetch()); }}>
        {t('common.retry', { defaultValue: 'Retry' })}
      </button>
    </div>;
  }
  if (!hasOwn && (!named.isSuccess || !region.data)) {
    return <span role="status">{t('common.loading', { defaultValue: 'Loading...' })}</span>;
  }
  const { missing, partial } = calendarCoverageProblems(schedule, region.data?.holiday_coverage);
  return <div className="min-w-0 max-w-full text-sm">
    {!hasOwn && region.data && <span>{t('schedule.work_calendar', {
      defaultValue: '{{hours}}h/day, {{days}} days/week',
      hours: String(region.data.hours_per_day), days: String(region.data.work_days_per_week),
    })}</span>}
    {(hasOwn ? own?.week_fallback === true : region.data?.week_fallback === true) && <p role="status" className="text-semantic-warning">
      {t('schedule.calendar.week_fallback', { defaultValue: 'The regional working week is unavailable. A standard planning week is used.' })}
    </p>}
    {missing.length > 0 && <p role="status" className="text-semantic-warning">
      {t('schedule.calendar.holidays_missing', { defaultValue: 'Public holidays are not available for {{years}}. Check the calendar before relying on these dates.', years: missing.join(', ') })}
    </p>}
    {partial.length > 0 && <p role="status" className="text-semantic-warning">
      {t('schedule.calendar.holidays_partial', { defaultValue: 'Public holiday coverage is incomplete for {{years}}. Check the calendar before relying on these dates.', years: partial.join(', ') })}
    </p>}
  </div>;
}
