// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Client-side CSV export of the (filtered) phone log, so a whole call history
// can be handed to a claim, an audit, or a spreadsheet. Same Blob + object-URL
// download pattern the analytics page uses, with no added dependency. Every
// cell is quoted per RFC 4180 when it holds a comma, quote, or newline, so a
// transcript or a party list never breaks the column layout.

import type { PhoneLog } from './types';
import { formatDuration } from './labels';

type TFn = (k: string, o: { defaultValue: string }) => string;

function cell(value: string | number | null | undefined): string {
  const s = value == null ? '' : String(value);
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Build the CSV text for a set of phone logs (header row + one row per call). */
export function buildPhoneLogCsv(logs: PhoneLog[], t: TFn): string {
  const headers = [
    t('phonelog.export_col_when', { defaultValue: 'When' }),
    t('phonelog.export_col_direction', { defaultValue: 'Direction' }),
    t('phonelog.export_col_channel', { defaultValue: 'Channel' }),
    t('phonelog.export_col_parties', { defaultValue: 'Parties' }),
    t('phonelog.export_col_duration', { defaultValue: 'Duration' }),
    t('phonelog.export_col_summary', { defaultValue: 'Summary' }),
    t('phonelog.export_col_instructions', { defaultValue: 'Instructions' }),
    t('phonelog.export_col_words', { defaultValue: 'Words' }),
  ];
  const rows = logs.map((log) =>
    [
      cell((log.occurred_at || log.created_at || '').replace('T', ' ')),
      cell(log.direction),
      cell(log.channel),
      cell(log.parties.join('; ')),
      // duration_seconds is an integer count, not a Decimal string, so plain
      // formatting is safe here.
      cell(formatDuration(t, log.duration_seconds)),
      cell(log.summary),
      cell(log.instructions.join(' | ')),
      cell(log.word_count),
    ].join(','),
  );
  return [headers.map(cell).join(','), ...rows].join('\r\n');
}

/** Build the CSV and trigger a browser download. No-op on an empty set. */
export function exportPhoneLogsCsv(logs: PhoneLog[], t: TFn): void {
  if (logs.length === 0) return;
  const csv = buildPhoneLogCsv(logs, t);
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'phone-log.csv';
  a.click();
  URL.revokeObjectURL(url);
}
