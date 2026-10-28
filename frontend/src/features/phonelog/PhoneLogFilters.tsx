// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Search + filter bar for the phone log. The list endpoint only narrows by
// direction and channel, so party / summary text and the date window are
// matched here over the fetched calls. Also carries the result count, a Clear
// control, and the Export CSV button.

import { useTranslation } from 'react-i18next';
import { Download, Search, X } from 'lucide-react';
import { Card } from '@/shared/ui';
import { CHANNELS, DIRECTIONS, channelLabel, directionLabel } from './labels';
import type { PhoneChannel, PhoneDirection, PhoneLog } from './types';

export interface PhoneLogFilterState {
  /** Free text matched against parties, summary, transcript, and instructions. */
  query: string;
  direction: '' | PhoneDirection;
  channel: '' | PhoneChannel;
  /** Inclusive date window (yyyy-mm-dd), matched against occurred_at. */
  from: string;
  to: string;
}

export const EMPTY_FILTER: PhoneLogFilterState = {
  query: '',
  direction: '',
  channel: '',
  from: '',
  to: '',
};

export function isFilterActive(f: PhoneLogFilterState): boolean {
  return (
    f.query.trim() !== '' ||
    f.direction !== '' ||
    f.channel !== '' ||
    f.from !== '' ||
    f.to !== ''
  );
}

/** Apply the filter over an already-fetched list of calls. */
export function filterPhoneLogs(logs: PhoneLog[], f: PhoneLogFilterState): PhoneLog[] {
  const q = f.query.trim().toLowerCase();
  return logs.filter((log) => {
    if (f.direction && log.direction !== f.direction) return false;
    if (f.channel && log.channel !== f.channel) return false;
    if (f.from || f.to) {
      // yyyy-mm-dd string compare is chronologically correct for a date window.
      const when = (log.occurred_at || log.created_at || '').slice(0, 10);
      if (!when) return false;
      if (f.from && when < f.from) return false;
      if (f.to && when > f.to) return false;
    }
    if (q) {
      const hay = [log.parties.join(' '), log.summary, log.transcript, log.instructions.join(' ')]
        .join(' ')
        .toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

const CONTROL =
  'rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm text-content-primary';

export function PhoneLogFilters({
  value,
  onChange,
  total,
  shown,
  onExport,
}: {
  value: PhoneLogFilterState;
  onChange: (next: PhoneLogFilterState) => void;
  total: number;
  shown: number;
  onExport: () => void;
}) {
  const { t } = useTranslation();
  const active = isFilterActive(value);
  const set = <K extends keyof PhoneLogFilterState>(key: K, v: PhoneLogFilterState[K]) =>
    onChange({ ...value, [key]: v });

  return (
    <Card className="space-y-3 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[12rem] flex-1">
          <Search className="pointer-events-none absolute inset-y-0 start-2 my-auto h-4 w-4 text-content-tertiary" />
          <input
            value={value.query}
            onChange={(e) => set('query', e.target.value)}
            placeholder={t('phonelog.search_ph', {
              defaultValue: 'Search party, summary, or what was said',
            })}
            aria-label={t('phonelog.search', { defaultValue: 'Search calls' })}
            className={`${CONTROL} w-full ps-8`}
          />
        </div>

        <select
          value={value.direction}
          onChange={(e) => set('direction', e.target.value as PhoneLogFilterState['direction'])}
          aria-label={t('phonelog.direction', { defaultValue: 'Direction' })}
          className={CONTROL}
        >
          <option value="">{t('phonelog.filter_all_directions', { defaultValue: 'All directions' })}</option>
          {DIRECTIONS.map((d) => (
            <option key={d} value={d}>
              {directionLabel(t, d)}
            </option>
          ))}
        </select>

        <select
          value={value.channel}
          onChange={(e) => set('channel', e.target.value as PhoneLogFilterState['channel'])}
          aria-label={t('phonelog.channel', { defaultValue: 'Channel' })}
          className={CONTROL}
        >
          <option value="">{t('phonelog.filter_all_channels', { defaultValue: 'All channels' })}</option>
          {CHANNELS.map((c) => (
            <option key={c} value={c}>
              {channelLabel(t, c)}
            </option>
          ))}
        </select>

        <button
          type="button"
          onClick={onExport}
          disabled={shown === 0}
          className="inline-flex items-center gap-1.5 rounded-md border border-border-light px-2.5 py-1.5 text-sm font-medium text-content-secondary hover:bg-surface-secondary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Download className="h-4 w-4" />
          {t('phonelog.export_csv', { defaultValue: 'Export CSV' })}
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <label className="inline-flex items-center gap-1.5 text-xs text-content-secondary">
          {t('phonelog.date_from', { defaultValue: 'From' })}
          <input
            type="date"
            value={value.from}
            max={value.to || undefined}
            onChange={(e) => set('from', e.target.value)}
            className={CONTROL}
          />
        </label>
        <label className="inline-flex items-center gap-1.5 text-xs text-content-secondary">
          {t('phonelog.date_to', { defaultValue: 'To' })}
          <input
            type="date"
            value={value.to}
            min={value.from || undefined}
            onChange={(e) => set('to', e.target.value)}
            className={CONTROL}
          />
        </label>

        <div className="ms-auto inline-flex items-center gap-2 text-xs text-content-tertiary">
          <span aria-live="polite">
            {active
              ? t('phonelog.result_count_filtered', {
                  defaultValue: 'Showing {{shown}} of {{total}}',
                  shown,
                  total,
                })
              : t('phonelog.result_count', { defaultValue: '{{total}} calls', total })}
          </span>
          {active && (
            <button
              type="button"
              onClick={() => onChange(EMPTY_FILTER)}
              className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 font-medium text-oe-blue-text hover:bg-surface-secondary"
            >
              <X className="h-3.5 w-3.5" />
              {t('phonelog.clear_filters', { defaultValue: 'Clear' })}
            </button>
          )}
        </div>
      </div>
    </Card>
  );
}
