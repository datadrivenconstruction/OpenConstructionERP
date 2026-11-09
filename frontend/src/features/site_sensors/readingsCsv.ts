// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pasted or imported readings: one `time,value[,note]` per line, parsed into
 * rows the API takes and the row errors shown in the preview before saving.
 * Separators: comma, semicolon or tab; with a semicolon or tab, a decimal
 * comma is accepted. A first line that is not a reading is taken as a header.
 */
import type { UserReading } from './api';

export const MAX_IMPORT_ROWS = 5000;

export type CsvRowError = 'bad_time' | 'bad_value' | 'duplicate_time' | 'too_many';

export interface CsvPreviewRow {
  line: number;
  raw: string;
  reading: UserReading | null;
  error: CsvRowError | null;
}

function splitLine(line: string): { cells: string[]; sep: string } {
  for (const sep of ['\t', ';', ',']) {
    if (line.includes(sep)) return { cells: line.split(sep).map((c) => c.trim()), sep };
  }
  return { cells: [line.trim()], sep: '' };
}

/** ISO instant from `2026-11-02T08:00`, `2026-11-02 08:00:00`, with or without a zone; local time when none. */
export function parseTime(text: string): string | null {
  const s = text.trim().replace(/^"|"$/g, '');
  if (!/^\d{4}-\d{2}-\d{2}([ T]\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?)?(Z|[+-]\d{2}:?\d{2})?$/.test(s)) return null;
  const d = new Date(s.includes(' ') ? s.replace(' ', 'T') : s);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

function parseValue(text: string, sep: string): number | null {
  let s = text.trim().replace(/^"|"$/g, '');
  if (sep !== ',' && /^-?\d+,\d+$/.test(s)) s = s.replace(',', '.');
  if (s === '' || !/^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(s)) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

/** Every non-blank line as a preview row; a leading header line is dropped. */
export function parseReadingsCsv(text: string): CsvPreviewRow[] {
  const lines = text.split(/\r?\n/);
  const rows: CsvPreviewRow[] = [];
  const seen = new Set<string>();
  let first = true;
  lines.forEach((raw, i) => {
    if (!raw.trim()) return;
    const { cells, sep } = splitLine(raw);
    const at = parseTime(cells[0] ?? '');
    const value = cells.length > 1 ? parseValue(cells[1] ?? '', sep) : null;
    if (first && at === null && value === null) {
      first = false;
      return;
    }
    first = false;
    let error: CsvRowError | null = null;
    if (at === null) error = 'bad_time';
    else if (value === null) error = 'bad_value';
    else if (seen.has(at)) error = 'duplicate_time';
    else if (seen.size >= MAX_IMPORT_ROWS) error = 'too_many';
    if (at !== null && error === null) seen.add(at);
    const note = cells.slice(2).join(sep || ',').trim().replace(/^"|"$/g, '').slice(0, 500);
    rows.push({
      line: i + 1,
      raw,
      reading: error === null && at !== null && value !== null ? { recorded_at: at, value, ...(note ? { note } : {}) } : null,
      error,
    });
  });
  return rows;
}

/** The readings of a preview that can be saved. */
export function validReadings(rows: readonly CsvPreviewRow[]): UserReading[] {
  return rows.flatMap((r) => (r.reading ? [r.reading] : []));
}
