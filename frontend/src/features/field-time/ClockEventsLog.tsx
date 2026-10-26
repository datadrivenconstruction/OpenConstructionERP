// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Clock events log - the last two weeks, day by day and worker by worker​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠. A
 * shift with no clock-out is highlighted. "Build timesheet for this day" turns
 * the day's clock shifts into a draft timesheet, shows the validation result
 * and opens the draft in the timesheet editor.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, ClipboardCheck, Loader2 } from 'lucide-react';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { ValidationPanel } from './ValidationPanel';
import { buildClockTimesheet, fetchClockValidation, useClockEvents } from './clockApi';
import { groupClockEvents, twoWeeksAgo } from './clockLog';

function hhmm(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function DayValidation({ projectId, date }: { projectId: string; date: string }) {
  const q = useQuery({
    queryKey: ['field-time', 'clock', 'validation', projectId, date],
    queryFn: () => fetchClockValidation(projectId, date),
  });
  return <ValidationPanel report={q.data} isLoading={q.isLoading} />;
}

export function ClockEventsLog({
  projectId,
  onOpenTimesheet,
}: {
  projectId: string;
  onOpenTimesheet: (timesheetId: string) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [building, setBuilding] = useState<string | null>(null);
  const [validated, setValidated] = useState<Record<string, string>>({});

  const from = useMemo(() => twoWeeksAgo(), []);
  const q = useClockEvents(projectId, { date_from: from });
  const days = useMemo(() => groupClockEvents(q.data?.items ?? []), [q.data]);

  const build = async (date: string) => {
    setBuilding(date);
    try {
      const ts = await buildClockTimesheet(projectId, date);
      setValidated((s) => ({ ...s, [date]: ts.id }));
    } catch (e) {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });
    } finally {
      setBuilding(null);
    }
  };

  if (q.isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-12 text-sm text-content-tertiary">
        <Loader2 size={16} className="animate-spin" />
        {t('common.loading', { defaultValue: 'Loading...' })}
      </div>
    );
  }
  if (q.isError) {
    return <p className="py-8 text-center text-sm text-semantic-error">{getErrorMessage(q.error)}</p>;
  }
  if (days.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-content-tertiary">
        {t('field_clock.log_empty', { defaultValue: 'No clock events in the last two weeks.' })}
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {days.map((day) => (
        <section key={day.date} className="rounded-xl border border-border-light bg-surface-primary">
          <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border-light px-4 py-3">
            <h3 className="text-sm font-semibold text-content-primary">
              <DateDisplay value={day.date} />
            </h3>
            <button
              type="button"
              disabled={building === day.date}
              onClick={() => void build(day.date)}
              className="inline-flex min-h-[44px] items-center gap-2 rounded-lg border border-border-light px-3 text-sm font-medium text-content-primary disabled:opacity-50"
            >
              {building === day.date ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <ClipboardCheck size={14} />
              )}
              {t('field_clock.build_timesheet', { defaultValue: 'Build timesheet for this day' })}
            </button>
          </header>
          <ul className="divide-y divide-border-light">
            {day.workers.map((w) => (
              <li
                key={w.resourceId}
                className={
                  w.missingOut ? 'bg-semantic-warning-bg px-4 py-3' : 'px-4 py-3'
                }
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-content-primary">{w.resourceName}</span>
                  {w.missingOut && (
                    <span className="inline-flex items-center gap-1 text-xs font-semibold text-semantic-warning">
                      <AlertTriangle size={13} />
                      {t('field_clock.missing_out', { defaultValue: 'No clock-out' })}
                    </span>
                  )}
                  {w.open && (
                    <span className="text-xs text-content-tertiary">
                      {t('field_clock.still_on_site', { defaultValue: 'Still on site' })}
                    </span>
                  )}
                  {w.pending > 0 && (
                    <span className="text-xs text-semantic-warning">
                      {t('field_clock.pending_count', {
                        defaultValue_one: '{{count}} awaiting approval',
                        defaultValue_other: '{{count}} awaiting approval',
                        count: w.pending,
                      })}
                    </span>
                  )}
                </div>
                <p className="mt-1 text-xs tabular-nums text-content-secondary">
                  {w.events
                    .map((e) => `${e.kind === 'in' ? '→' : '←'} ${hhmm(e.occurred_at)}`)
                    .join('   ')}
                </p>
              </li>
            ))}
          </ul>
          {validated[day.date] && (
            <div className="space-y-2 border-t border-border-light p-3">
              <DayValidation projectId={projectId} date={day.date} />
              <button
                type="button"
                onClick={() => onOpenTimesheet(validated[day.date] as string)}
                className="min-h-[44px] rounded-lg bg-oe-blue px-4 text-sm font-semibold text-content-inverse"
              >
                {t('field_clock.open_timesheet', { defaultValue: 'Open the timesheet' })}
              </button>
            </div>
          )}
        </section>
      ))}
    </div>
  );
}
