// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Client-side triage controls for the inbound-capture read surface. The read
// endpoint only paginates (offset / limit), so search, channel, date-range and
// has-attachment refinement run over the page that is currently fetched. The
// filter itself is a pure function so it stays trivially testable and the page
// component only owns state.

import { useTranslation } from 'react-i18next';
import { Paperclip, Search, X } from 'lucide-react';

import { Input } from '@/shared/ui';
import type { InboundMessage } from './types';

/** Refinement applied over the currently fetched page of captured messages. */
export interface InboundFilterState {
  /** Free text matched against sender, subject, reference and recipients. */
  q: string;
  /** Exact channel match (email / chat / ...); empty means any channel. */
  channel: string;
  /** Inclusive lower bound on sent_at, as a yyyy-mm-dd string; empty = open. */
  from: string;
  /** Inclusive upper bound on sent_at, as a yyyy-mm-dd string; empty = open. */
  to: string;
  /** When true, keep only messages that carry at least one attachment. */
  withAttachments: boolean;
}

export const EMPTY_INBOUND_FILTERS: InboundFilterState = {
  q: '',
  channel: '',
  from: '',
  to: '',
  withAttachments: false,
};

/** True when any refinement is set, so the page can show a clear affordance. */
export function hasActiveInboundFilters(f: InboundFilterState): boolean {
  return (
    f.q.trim().length > 0 ||
    f.channel.length > 0 ||
    f.from.length > 0 ||
    f.to.length > 0 ||
    f.withAttachments
  );
}

/** The distinct channels present in a page, for the channel dropdown. */
export function inboundChannels(items: InboundMessage[]): string[] {
  return Array.from(new Set(items.map((m) => m.channel).filter(Boolean))).sort();
}

/**
 * Apply the refinement to a page of messages. Pure: no state, no I/O. Messages
 * whose sent_at cannot be parsed are dropped only when a date bound is active
 * (they cannot be confirmed inside the window); otherwise they are kept.
 */
export function filterInboundMessages(
  items: InboundMessage[],
  f: InboundFilterState,
): InboundMessage[] {
  const q = f.q.trim().toLowerCase();
  const from = f.from ? Date.parse(`${f.from}T00:00:00`) : null;
  const to = f.to ? Date.parse(`${f.to}T23:59:59.999`) : null;

  return items.filter((m) => {
    if (f.withAttachments && m.attachments.length === 0) return false;
    if (f.channel && m.channel !== f.channel) return false;

    if (q) {
      const haystack = [m.sender, m.subject, m.reference_number, ...(m.recipients ?? [])]
        .join(' ')
        .toLowerCase();
      if (!haystack.includes(q)) return false;
    }

    if (from != null || to != null) {
      const ts = Date.parse(m.sent_at);
      if (Number.isNaN(ts)) return false;
      if (from != null && ts < from) return false;
      if (to != null && ts > to) return false;
    }

    return true;
  });
}

/* Native select / date control - matched to the Input height so the row lines
   up. The select keeps its native arrow (no appearance-none) for a11y. */
const controlCls =
  'h-9 rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary ' +
  'focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const labelCls = 'mb-1.5 block text-xs font-medium text-content-secondary';

export function InboundFilters({
  value,
  onChange,
  channels,
}: {
  value: InboundFilterState;
  onChange: (next: InboundFilterState) => void;
  channels: string[];
}) {
  const { t } = useTranslation();
  const active = hasActiveInboundFilters(value);

  const set = <K extends keyof InboundFilterState>(key: K, v: InboundFilterState[K]) =>
    onChange({ ...value, [key]: v });

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
      <div className="min-w-0 flex-1 sm:max-w-xs">
        <label htmlFor="inbound-search" className={labelCls}>
          {t('inbound.filter_search_label', { defaultValue: 'Search' })}
        </label>
        <Input
          id="inbound-search"
          value={value.q}
          onChange={(e) => set('q', e.target.value)}
          icon={<Search className="h-4 w-4" aria-hidden />}
          placeholder={t('inbound.filter_search_ph', { defaultValue: 'Sender or subject' })}
        />
      </div>

      <div>
        <label htmlFor="inbound-channel" className={labelCls}>
          {t('inbound.filter_channel_label', { defaultValue: 'Channel' })}
        </label>
        <select
          id="inbound-channel"
          value={value.channel}
          onChange={(e) => set('channel', e.target.value)}
          className={`${controlCls} pr-8`}
        >
          <option value="">
            {t('inbound.filter_all_channels', { defaultValue: 'All channels' })}
          </option>
          {channels.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="inbound-from" className={labelCls}>
          {t('inbound.filter_from_label', { defaultValue: 'From' })}
        </label>
        <input
          id="inbound-from"
          type="date"
          value={value.from}
          max={value.to || undefined}
          onChange={(e) => set('from', e.target.value)}
          className={controlCls}
        />
      </div>

      <div>
        <label htmlFor="inbound-to" className={labelCls}>
          {t('inbound.filter_to_label', { defaultValue: 'To' })}
        </label>
        <input
          id="inbound-to"
          type="date"
          value={value.to}
          min={value.from || undefined}
          onChange={(e) => set('to', e.target.value)}
          className={controlCls}
        />
      </div>

      <div className="flex h-9 items-center gap-4">
        <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-content-secondary">
          <input
            type="checkbox"
            checked={value.withAttachments}
            onChange={(e) => set('withAttachments', e.target.checked)}
            className="h-4 w-4 shrink-0 accent-oe-blue"
          />
          <span className="inline-flex items-center gap-1">
            <Paperclip className="h-3.5 w-3.5" aria-hidden />
            {t('inbound.filter_has_attachment', { defaultValue: 'Has attachment' })}
          </span>
        </label>

        {active ? (
          <button
            type="button"
            onClick={() => onChange(EMPTY_INBOUND_FILTERS)}
            className="inline-flex items-center gap-1 text-sm text-content-tertiary hover:text-content-secondary"
          >
            <X className="h-3.5 w-3.5" aria-hidden />
            {t('inbound.filter_clear', { defaultValue: 'Clear' })}
          </button>
        ) : null}
      </div>
    </div>
  );
}
