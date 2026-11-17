// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Column mapping for survey point files (pure, no React).
 *
 * The dialog guesses the delimiter and the column order and shows both with a
 * confidence; the person can change either before anything is read for real.
 * The server reads the file again with the mapping the person confirmed.
 */

import type { FileFormat } from './api';

export type ColumnField = '' | 'point_id' | 'e' | 'n' | 'z' | 'code' | 'description' | 'kind' | 'sigma';
export const COLUMN_FIELDS: ColumnField[] = ['point_id', 'e', 'n', 'z', 'code', 'description', 'kind', 'sigma'];

export type PresetName = 'PNEZD' | 'PENZD' | 'ENZ' | 'NEZ';
export const PRESETS: Record<PresetName, ColumnField[]> = {
  PNEZD: ['point_id', 'n', 'e', 'z', 'code'],
  PENZD: ['point_id', 'e', 'n', 'z', 'code'],
  ENZ: ['e', 'n', 'z'],
  NEZ: ['n', 'e', 'z'],
};
export const PRESET_NAMES = Object.keys(PRESETS) as PresetName[];

export const DELIMITERS = [',', ';', '\t', '|', ' '] as const;

export interface Guess<T> {
  value: T;
  confidence: number;
}

function dataLines(text: string): string[] {
  return text
    .replace(/^﻿/, '')
    .split(/\r?\n/)
    .filter((l) => l.trim() !== '' && !l.trimStart().startsWith('#'));
}

/** One line split on a delimiter; a space means any run of blanks. Quotes are honoured for the rest. */
export function splitLine(line: string, delimiter: string): string[] {
  if (delimiter === ' ') return line.trim().split(/\s+/);
  const out: string[] = [];
  let cur = '';
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (ch === '"') {
      if (quoted && line[i + 1] === '"') {
        cur += '"';
        i += 1;
      } else {
        quoted = !quoted;
      }
    } else if (ch === delimiter && !quoted) {
      out.push(cur.trim());
      cur = '';
    } else {
      cur += ch;
    }
  }
  out.push(cur.trim());
  return out;
}

/** The delimiter that splits the first rows into the same number of columns. */
export function detectDelimiter(text: string): Guess<string> {
  const sample = dataLines(text).slice(0, 20);
  if (sample.length === 0) return { value: ',', confidence: 0 };
  let best: Guess<string> = { value: ',', confidence: 0 };
  for (const d of DELIMITERS) {
    const counts = sample.map((l) => splitLine(l, d).length);
    if (Math.min(...counts) < 2) continue;
    const freq = new Map<number, number>();
    counts.forEach((c) => freq.set(c, (freq.get(c) ?? 0) + 1));
    let score = Math.max(...freq.values()) / counts.length;
    if (d === ' ') score *= 0.9;
    if (score > best.confidence) best = { value: d, confidence: Math.round(score * 100) / 100 };
  }
  return best;
}

export function parseNumber(raw: string | undefined): number | null {
  if (raw == null) return null;
  let s = raw.trim().replace(/\s/g, '');
  if (!s) return null;
  if (s.includes(',') && !s.includes('.')) s = s.replace(',', '.');
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

const HEADER_WORDS: Record<string, ColumnField> = {
  point: 'point_id', pt: 'point_id', id: 'point_id', name: 'point_id', p: 'point_id', number: 'point_id',
  e: 'e', east: 'e', easting: 'e',
  n: 'n', north: 'n', northing: 'n',
  z: 'z', h: 'z', elev: 'z', elevation: 'z', height: 'z', rl: 'z',
  code: 'code', d: 'code', desc: 'code', description: 'code',
};

export function headerField(cell: string): ColumnField | null {
  return HEADER_WORDS[cell.trim().toLowerCase().replace(/[^a-z_]/g, '')] ?? null;
}

/** True when the first row reads as column names rather than a point. */
export function looksLikeHeader(rows: string[][]): boolean {
  const first = rows[0];
  if (!first) return false;
  const fields = first.map(headerField);
  return fields.includes('e') && fields.includes('n');
}

/**
 * The likely column order. Header names decide; otherwise magnitudes: a
 * projected northing is usually far larger than the easting (UTM: 7 digits
 * against 6), so the larger column is read as N. On a local grid the two are
 * alike and the confidence says so.
 */
export function guessPreset(rows: string[][]): Guess<PresetName> {
  if (rows.length === 0) return { value: 'PENZD', confidence: 0 };
  if (looksLikeHeader(rows)) {
    const head = rows[0]!.map(headerField);
    const eFirst = head.indexOf('e') < head.indexOf('n');
    const withId = head[0] === 'point_id';
    return { value: withId ? (eFirst ? 'PENZD' : 'PNEZD') : eFirst ? 'ENZ' : 'NEZ', confidence: 0.95 };
  }
  const data = rows.filter((r) => r.length >= 3);
  if (data.length === 0) return { value: 'PENZD', confidence: 0 };
  const firstNumeric = data.slice(0, 20).every((r) => parseNumber(r[0]) !== null);
  const withId = !firstNumeric || data[0]!.length >= 4;
  const [a, b] = withId ? [1, 2] : [0, 1];
  const votes = data
    .slice(0, 50)
    .map((r) => [parseNumber(r[a]), parseNumber(r[b])] as const)
    .filter((v): v is readonly [number, number] => v[0] !== null && v[1] !== null);
  if (votes.length === 0) return { value: withId ? 'PENZD' : 'ENZ', confidence: 0.3 };
  const firstBigger = votes.filter(([x, y]) => Math.abs(x) > Math.abs(y) * 2).length / votes.length;
  const secondBigger = votes.filter(([x, y]) => Math.abs(y) > Math.abs(x) * 2).length / votes.length;
  const round = (v: number) => Math.round(v * 100) / 100;
  if (firstBigger >= 0.8) return { value: withId ? 'PNEZD' : 'NEZ', confidence: round(0.6 + 0.3 * firstBigger) };
  if (secondBigger >= 0.8) return { value: withId ? 'PENZD' : 'ENZ', confidence: round(0.6 + 0.3 * secondBigger) };
  return { value: withId ? 'PENZD' : 'ENZ', confidence: 0.4 };
}

/** The preset's fields laid over the file's columns; extra columns are not imported. */
export function columnsForPreset(preset: PresetName, columnCount: number): ColumnField[] {
  const fields = PRESETS[preset];
  return Array.from({ length: Math.max(columnCount, 0) }, (_, i) => fields[i] ?? '');
}

/** Which preset a mapping equals, if any. */
export function presetOf(columns: ColumnField[]): PresetName | null {
  const trimmed = [...columns];
  while (trimmed.length && trimmed[trimmed.length - 1] === '') trimmed.pop();
  return PRESET_NAMES.find((p) => PRESETS[p].join(',') === trimmed.join(',')) ?? null;
}

/** Choosing a field already used by another column moves it; a field feeds one column only. */
export function chooseColumn(columns: ColumnField[], index: number, field: ColumnField): ColumnField[] {
  return columns.map((f, i) => (i === index ? field : field && f === field ? '' : f));
}

export type MappingProblem = 'missing_e' | 'missing_n';

export function mappingProblems(columns: ColumnField[]): MappingProblem[] {
  const out: MappingProblem[] = [];
  if (!columns.includes('e')) out.push('missing_e');
  if (!columns.includes('n')) out.push('missing_n');
  return out;
}

export function fileFormatFor(filename: string): FileFormat {
  const ext = filename.toLowerCase().split('.').pop() ?? '';
  if (ext === 'geojson' || ext === 'json') return 'geojson';
  if (ext === 'txt' || ext === 'pts' || ext === 'xyz') return 'txt';
  return 'csv';
}

/** First rows of the file split for the mapping table. */
export function sampleRows(text: string, delimiter: string, count = 5): string[][] {
  return dataLines(text)
    .slice(0, count)
    .map((l) => splitLine(l, delimiter));
}

/** A delimiter as a person reads it. */
export function delimiterLabelKey(d: string): string {
  return { ',': 'comma', ';': 'semicolon', '\t': 'tab', '|': 'pipe', ' ': 'space' }[d] ?? 'comma';
}
