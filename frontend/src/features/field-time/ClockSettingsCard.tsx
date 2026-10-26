// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Clock settings card - switch the clock on, how long positions are kept, the unpaid break, purge now​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠. */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  purgeClockPositions,
  useClockSettings,
  useSaveClockSettings,
} from './clockApi';

export function ClockSettingsCard({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const q = useClockSettings(projectId);
  const save = useSaveClockSettings(projectId);
  const [enabled, setEnabled] = useState(false);
  const [retention, setRetention] = useState('30');
  const [breakMin, setBreakMin] = useState('0');
  const [purging, setPurging] = useState(false);

  useEffect(() => {
    if (!q.data) return;
    setEnabled(q.data.enabled);
    setRetention(String(q.data.retention_days));
    setBreakMin(String(q.data.default_break_minutes ?? 0));
  }, [q.data]);

  const retentionN = Math.round(Number(retention));
  const breakN = Math.round(Number(breakMin));
  const valid = retentionN >= 1 && Number.isFinite(retentionN) && breakN >= 0 && breakN <= 240;

  const onSave = async () => {
    if (!q.data || !valid) return;
    try {
      await save.mutateAsync({
        ...q.data,
        enabled,
        retention_days: retentionN,
        default_break_minutes: breakN,
      });
      addToast({ type: 'success', title: t('field_clock.settings_saved', { defaultValue: 'Settings saved' }) });
    } catch (e) {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });
    }
  };

  const onPurge = async () => {
    if (
      !window.confirm(
        t('field_clock.purge_confirm', {
          defaultValue: 'Delete every stored clock position older than the retention period now?',
        }),
      )
    )
      return;
    setPurging(true);
    try {
      const r = await purgeClockPositions(projectId);
      addToast({
        type: 'success',
        title: t('field_clock.purged', {
          defaultValue_one: '{{count}} position deleted',
          defaultValue_other: '{{count}} positions deleted',
          count: r.purged,
        }),
      });
    } catch (e) {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) });
    } finally {
      setPurging(false);
    }
  };

  const input = 'h-11 w-full rounded-lg border border-border-light bg-surface-primary px-3 text-sm text-content-primary';
  const label = 'mb-1 block text-xs font-medium text-content-secondary';

  if (q.isLoading) {
    return <Loader2 size={16} className="m-6 animate-spin text-content-tertiary" />;
  }
  if (q.isError) {
    return <p className="py-8 text-center text-sm text-semantic-error">{getErrorMessage(q.error)}</p>;
  }

  return (
    <div className="max-w-lg space-y-4 rounded-xl border border-border-light bg-surface-primary p-4">
      <label className="flex min-h-[44px] items-center gap-3 text-sm font-medium text-content-primary">
        <input
          type="checkbox"
          className="h-5 w-5"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
        />
        {t('field_clock.enable', { defaultValue: 'Enable the time clock for this project' })}
      </label>

      <div>
        <label htmlFor="clock-retention" className={label}>
          {t('field_clock.retention_days', { defaultValue: 'Keep clock positions for (days)' })}
        </label>
        <input
          id="clock-retention"
          inputMode="numeric"
          className={input}
          value={retention}
          onChange={(e) => setRetention(e.target.value)}
        />
        <p className="mt-1 text-2xs text-content-tertiary">
          {t('field_clock.retention_hint', {
            defaultValue: 'After this the position is deleted. The clock times stay on the timesheet.',
          })}
        </p>
      </div>

      <div>
        <label htmlFor="clock-break" className={label}>
          {t('field_clock.break_minutes', { defaultValue: 'Unpaid break per shift (minutes)' })}
        </label>
        <input
          id="clock-break"
          inputMode="numeric"
          className={input}
          value={breakMin}
          onChange={(e) => setBreakMin(e.target.value)}
        />
        <p className="mt-1 text-2xs text-content-tertiary">
          {t('field_clock.break_hint', { defaultValue: 'Deducted from each shift when a timesheet is built (0 to 240).' })}
        </p>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row">
        <button
          type="button"
          disabled={!valid || save.isPending}
          onClick={() => void onSave()}
          className="inline-flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-lg bg-oe-blue px-4 text-sm font-semibold text-content-inverse disabled:opacity-50"
        >
          {save.isPending && <Loader2 size={15} className="animate-spin" />}
          {t('common.save', { defaultValue: 'Save' })}
        </button>
        <button
          type="button"
          disabled={purging}
          onClick={() => void onPurge()}
          className="min-h-[44px] flex-1 rounded-lg border border-semantic-error px-4 text-sm font-semibold text-semantic-error disabled:opacity-50"
        >
          {t('field_clock.purge_now', { defaultValue: 'Purge old positions now' })}
        </button>
      </div>
    </div>
  );
}
