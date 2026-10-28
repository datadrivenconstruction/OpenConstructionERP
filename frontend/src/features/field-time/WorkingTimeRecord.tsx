// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * <WorkingTimeRecordPanel> - the statutory working-time record for a project.
 *
 * Some countries oblige an employer to record when each worker started and
 * stopped on each day, to have that record within a few days, and to keep it
 * for years. Most of this platform's users are under no such obligation, so the
 * whole surface is behind one choice: pick a regime and it appears, pick none
 * and nothing about it is ever asked of you. Nothing here refuses a record for
 * being late and nothing here deletes one for being old; it says which days
 * were recorded late and how long each has to be kept, and hands the lot over
 * as a file when an inspector asks.
 *
 * The rows are worker-days, not timesheet lines, because that is the unit the
 * question is asked in: this person, this day, from when to when.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Loader2, ScrollText, Download, AlertTriangle } from 'lucide-react';
import { Badge, Button, CollapsibleSection, EmptyState, ErrorState } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { todayLocalISO } from '@/shared/lib/dates';
import {
  fetchWorkingTimeRecord,
  downloadWorkingTimeRecord,
  listWorkingTimeRegimes,
  formatHours,
  type WorkingTimeWorkerDay,
} from './api';

/** First day of the month `todayISO` falls in, as an ISO date. */
function monthStart(todayISO: string): string {
  return `${todayISO.slice(0, 7)}-01`;
}

export interface WorkingTimeRecordPanelProps {
  projectId: string;
  /** The regime new timesheets are recorded under, or '' for none. */
  regime: string;
  onRegimeChange: (next: string) => void;
}

export function WorkingTimeRecordPanel({
  projectId,
  regime,
  onRegimeChange,
}: WorkingTimeRecordPanelProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const today = todayLocalISO();
  const [dateFrom, setDateFrom] = useState(monthStart(today));
  const [dateTo, setDateTo] = useState(today);
  const [downloading, setDownloading] = useState(false);

  const regimesQ = useQuery({
    queryKey: ['field-time', 'working-time-regimes'],
    queryFn: listWorkingTimeRegimes,
    staleTime: Infinity,
  });

  // The selected regime is what NEW days get recorded under. It is deliberately
  // not sent to the record or to the export: the server reads each day's regime
  // off the timesheet that day was booked on. Passing the selection here would
  // let anyone stamp a foreign country's deadlines onto days that were never
  // recorded under them, and a screen whose job is to say which days are late
  // must not call a day late under a rule it was never kept to.
  const recordQ = useQuery({
    queryKey: ['field-time', 'working-time', projectId, dateFrom, dateTo],
    queryFn: () => fetchWorkingTimeRecord(projectId, dateFrom, dateTo, null),
    enabled: !!projectId && !!dateFrom && !!dateTo,
  });

  const record = recordQ.data ?? null;
  const chosen = useMemo(
    () => (regimesQ.data ?? []).find((r) => r.code === (regime || record?.regime)) ?? null,
    [regimesQ.data, regime, record?.regime],
  );

  const onExport = async () => {
    setDownloading(true);
    try {
      // Same rule as the query above: the file has to say what the screen says.
      await downloadWorkingTimeRecord(projectId, dateFrom, dateTo, null);
    } catch (e) {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(e),
      });
    } finally {
      setDownloading(false);
    }
  };

  const fieldCls =
    'h-9 rounded-lg border border-border-light bg-surface-primary px-3 text-sm text-content-primary';

  return (
    <CollapsibleSection
      storageKey="field_time.working_time"
      icon={<ScrollText size={15} className="text-oe-blue" />}
      title={t('field_time.working_time.title', { defaultValue: 'Statutory working-time record' })}
      // Closed on a first visit, unlike the module explainer above it. This
      // block answers a question most of the world never asks, and the whole
      // point of the feature is that whoever does not need it never meets it.
      defaultCollapsed
    >
      <p className="text-xs text-content-tertiary">
        {t('field_time.working_time.intro', {
          defaultValue:
            'Some countries oblige an employer to record when each worker started and stopped on each day, to write it down within days rather than weeks, and to keep it for years. Choose the regime that applies to this site and the record is kept as the hours are booked. Choose none and nothing here asks anything of you.',
        })}
      </p>

      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="flex flex-col">
          <span className="mb-1 text-2xs font-medium text-content-tertiary">
            {/* Named for what it does. It sets the regime new days are booked
                under and deliberately does not filter the table below, so a
                label reading like a filter would look broken the moment
                somebody changed it and nothing moved. */}
            {t('field_time.working_time.regime', { defaultValue: 'Record new days under' })}
          </span>
          <select
            value={regime}
            onChange={(e) => onRegimeChange(e.target.value)}
            className={fieldCls}
          >
            <option value="">
              {t('field_time.working_time.regime_none', { defaultValue: 'None' })}
            </option>
            {(regimesQ.data ?? []).map((r) => (
              <option key={r.code} value={r.code}>
                {t(`field_time.working_time.regime_${r.code}`, { defaultValue: r.label })}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col">
          <span className="mb-1 text-2xs font-medium text-content-tertiary">
            {t('field_time.date_from', { defaultValue: 'From date' })}
          </span>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className={fieldCls}
          />
        </label>
        <label className="flex flex-col">
          <span className="mb-1 text-2xs font-medium text-content-tertiary">
            {t('field_time.date_to', { defaultValue: 'To date' })}
          </span>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className={fieldCls}
          />
        </label>
        <Button
          variant="secondary"
          size="md"
          icon={<Download size={15} />}
          loading={downloading}
          disabled={!record || record.days.length === 0}
          onClick={() => void onExport()}
        >
          {t('field_time.working_time.export', { defaultValue: 'Export for an audit' })}
        </Button>
      </div>

      {chosen && (
        <p className="mt-3 rounded-lg border border-border-light bg-surface-secondary/40 p-3 text-2xs leading-relaxed text-content-tertiary">
          <span className="font-semibold text-content-secondary">{chosen.provision}</span>{' '}
          {t(`field_time.working_time.summary_${chosen.code}`, { defaultValue: chosen.summary })}
        </p>
      )}

      {recordQ.isLoading ? (
        <div className="flex items-center justify-center gap-2 py-10 text-sm text-content-tertiary">
          <Loader2 size={16} className="animate-spin" />
          {t('common.loading', { defaultValue: 'Loading...' })}
        </div>
      ) : recordQ.isError ? (
        <ErrorState
          title={t('field_time.working_time.load_failed', {
            defaultValue: 'Could not load the working-time record',
          })}
          hint={getErrorMessage(recordQ.error)}
          onRetry={() => recordQ.refetch()}
        />
      ) : !record || record.days.length === 0 ? (
        <div className="mt-3">
          <EmptyState
            icon={<ScrollText size={24} strokeWidth={1.5} />}
            title={t('field_time.working_time.empty_title', {
              defaultValue: 'No worker days in this period',
            })}
            description={t('field_time.working_time.empty_hint', {
              defaultValue:
                'The record is built from the hours already booked here. Book a day, give its lines a start and an end, and it appears in this list.',
            })}
          />
        </div>
      ) : (
        <>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
            <Counter
              label={t('field_time.working_time.workers', { defaultValue: 'Workers' })}
              value={String(record.workers)}
            />
            <Counter
              label={t('field_time.working_time.worker_days', { defaultValue: 'Worker days' })}
              value={String(record.days.length)}
            />
            <Counter
              label={t('field_time.working_time.total_hours', { defaultValue: 'Hours' })}
              value={formatHours(record.total_hours)}
            />
            <Counter
              label={t('field_time.working_time.late_days', { defaultValue: 'Recorded late' })}
              value={String(record.late_days)}
              tone={record.late_days > 0 ? 'warning' : undefined}
            />
            <Counter
              label={t('field_time.working_time.missing_times', { defaultValue: 'Without times' })}
              value={String(record.days_missing_times)}
              tone={record.days_missing_times > 0 ? 'warning' : undefined}
            />
          </div>

          {record.excluded_corrections > 0 && (
            <p className="mt-2 text-2xs text-content-tertiary">
              {t('field_time.working_time.excluded', {
                defaultValue:
                  '{{count}} corrected timesheets are left out so the same hours are not counted twice.',
                count: record.excluded_corrections,
              })}
            </p>
          )}

          {!record.regime && (
            <p className="mt-2 flex items-start gap-1.5 text-2xs text-content-tertiary">
              <AlertTriangle size={13} className="mt-px shrink-0 text-semantic-warning" />
              {t('field_time.working_time.no_regime_hint', {
                defaultValue:
                  'No recording regime is set on these days, so nothing is said about when each record was due or how long it has to be kept. The times themselves are still listed.',
              })}
            </p>
          )}

          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[52rem] text-left text-xs">
              <thead className="border-b border-border-light text-2xs uppercase tracking-wide text-content-tertiary">
                <tr>
                  <th className="py-2 pr-3 font-medium">
                    {t('field_time.date', { defaultValue: 'Date' })}
                  </th>
                  <th className="py-2 pr-3 font-medium">
                    {t('field_time.worker', { defaultValue: 'Worker / crew' })}
                  </th>
                  <th className="py-2 pr-3 font-medium">
                    {t('field_time.working_time.employer', { defaultValue: 'Employer' })}
                  </th>
                  <th className="py-2 pr-3 font-medium">
                    {t('field_time.working_time.start', { defaultValue: 'Start' })}
                  </th>
                  <th className="py-2 pr-3 font-medium">
                    {t('field_time.working_time.end', { defaultValue: 'End' })}
                  </th>
                  <th className="py-2 pr-3 font-medium">
                    {t('field_time.working_time.break', { defaultValue: 'Break' })}
                  </th>
                  <th className="py-2 pr-3 font-medium">
                    {t('field_time.working_time.duration', { defaultValue: 'Duration' })}
                  </th>
                  <th className="py-2 pr-3 font-medium">
                    {t('field_time.working_time.recorded', { defaultValue: 'Recorded' })}
                  </th>
                  <th className="py-2 font-medium">
                    {t('field_time.working_time.retain_until', { defaultValue: 'Keep until' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {record.days.map((day) => (
                  <WorkerDayRow key={rowKey(day)} day={day} />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </CollapsibleSection>
  );
}

function rowKey(day: WorkingTimeWorkerDay): string {
  return `${day.date}:${day.resource_id ?? ''}:${day.employer_kind}:${day.employer_subcontractor_id ?? ''}`;
}

function WorkerDayRow({ day }: { day: WorkingTimeWorkerDay }) {
  const { t } = useTranslation();

  const employer =
    day.employer_kind === 'subcontractor'
      ? day.employer ||
        t('field_time.working_time.employer_unnamed', { defaultValue: 'Subcontractor, not named' })
      : day.employer_kind === 'own'
        ? t('field_time.working_time.employer_own', { defaultValue: 'Own staff' })
        : t('field_time.working_time.employer_unstated', { defaultValue: 'Not stated' });

  return (
    <tr className="border-b border-border-light/60 last:border-0">
      <td className="py-2 pr-3 whitespace-nowrap">
        <DateDisplay value={day.date} format="numeric" />
      </td>
      <td className="py-2 pr-3">{day.worker}</td>
      <td className="py-2 pr-3">
        <span className={day.employer_kind ? '' : 'text-content-tertiary'}>{employer}</span>
      </td>
      <td className="py-2 pr-3 tabular-nums">
        {day.started_at ? <DateDisplay value={day.started_at} format="time" /> : <Missing />}
      </td>
      <td className="py-2 pr-3 tabular-nums">
        {day.ended_at ? <DateDisplay value={day.ended_at} format="time" /> : <Missing />}
      </td>
      <td className="py-2 pr-3 tabular-nums">
        {day.break_minutes > 0
          ? t('field_time.working_time.minutes', {
              defaultValue: '{{count}} min',
              count: day.break_minutes,
            })
          : ''}
      </td>
      <td className="py-2 pr-3 tabular-nums">
        {t('field_time.hours_value', { defaultValue: '{{hours}} h', hours: formatHours(day.duration_hours) })}
        {day.segments_without_times > 0 && (
          <span className="ml-1.5 text-2xs text-semantic-warning">
            {t('field_time.working_time.partly_untimed', {
              defaultValue: '{{count}} bookings without times',
              count: day.segments_without_times,
            })}
          </span>
        )}
      </td>
      <td className="py-2 pr-3 whitespace-nowrap">
        {day.recorded_at ? <DateDisplay value={day.recorded_at} format="numeric" /> : <Missing />}
        {/* The badge reports the days the record took, not the days it ran over
            by: the window belongs to the regime, and doing that subtraction here
            would hard code one regime's number into a screen serving any. */}
        {day.late && (
          <Badge variant="warning" size="sm" className="ml-1.5">
            {t('field_time.working_time.late', {
              defaultValue: 'written up after {{count}} days',
              count: day.days_taken ?? 0,
            })}
          </Badge>
        )}
      </td>
      <td className="py-2 whitespace-nowrap">
        {day.retain_until ? (
          <span className={day.within_retention ? '' : 'text-content-tertiary'}>
            <DateDisplay value={day.retain_until} format="numeric" />
          </span>
        ) : (
          <Missing />
        )}
      </td>
    </tr>
  );
}

function Missing() {
  const { t } = useTranslation();
  return (
    <span className="text-content-tertiary" title={t('common.not_set', { defaultValue: 'Not set' })}>
      &mdash;
    </span>
  );
}

function Counter({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: 'warning';
}) {
  return (
    <div className="rounded-lg border border-border-light bg-surface-primary p-2.5">
      <div className="text-2xs text-content-tertiary">{label}</div>
      <div
        className={`mt-0.5 text-lg font-semibold tabular-nums ${
          tone === 'warning' ? 'text-semantic-warning' : 'text-content-primary'
        }`}
      >
        {value}
      </div>
    </div>
  );
}
