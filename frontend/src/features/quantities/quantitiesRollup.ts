// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Measured-quantities rollup helpers for the Quantity Takeoff hub.
 *
 * Pure, client-side aggregation over the two existing quantity sources of a
 * project:
 *   - PDF takeoff measurements  (`GET /v1/takeoff/measurements/`)
 *   - BOQ position quantities   (`GET /v1/boq/boqs/` + `/v1/boq/boqs/{id}`)
 *
 * No new endpoint is introduced. Every value is coerced through the canonical
 * `toNum` money/number primitive first, so a Decimal-as-string quantity from
 * the BOQ wire (e.g. `"12.5000"`) never string-concatenates or throws on a
 * `.toFixed`. Totals are summed as finite numbers (quantities are not money
 * cents) and the counts are always exact, so a group stays meaningful even
 * when a float sum carries the usual sub-unit rounding.
 *
 * Aggregation is always keyed by (group, unit) so a total NEVER mixes units:
 * summing 12 m2 with 3 m is nonsensical, so those land in separate rows.
 */

import { toNum } from '@/shared/lib/money';
import type { MeasurementResponse } from '../takeoff/api';
import { isSection, type Position } from '../boq/api';

/* ── Model ───────────────────────────────────────────────────────────── */

/** Where a measured quantity came from. */
export type QuantitySource = 'takeoff' | 'boq';

/** How the rollup rows are grouped. */
export type RollupDimension = 'unit' | 'trade' | 'kind' | 'source';

/** One normalized quantity row, source-agnostic. */
export interface QuantityRecord {
  source: QuantitySource;
  /** Canonical (stored) unit label, e.g. "m", "m2", "m3", "pcs". */
  unit: string;
  /** Trade / group label: takeoff group name, or BOQ classification / name. */
  trade: string;
  /** Kind: takeoff measurement type (area / distance / count / volume) or `boq_line`. */
  kind: string;
  /** Signed, finite quantity value (an opening / deduction is negative). */
  value: number;
  /** Human label kept for the CSV detail (annotation / description). */
  label: string;
  /** Takeoff document id (null for a BOQ line). */
  documentId: string | null;
}

/** One aggregated (group, unit) bucket. */
export interface RollupRow {
  group: string;
  unit: string;
  count: number;
  total: number;
  sources: QuantitySource[];
}

/** One per-unit grand total (drives the KPI strip). */
export interface UnitTotal {
  unit: string;
  count: number;
  total: number;
  sources: QuantitySource[];
}

/** Minimal shape of a fetched BOQ + its positions, fed into {@link boqsToRecords}. */
export interface BoqPositions {
  name: string;
  positions: Position[];
}

/** Placeholder group / unit label for a record that carries no unit. */
export const NO_UNIT = '-';

/**
 * Normalize a unit label so grouping keys stay stable across sources
 * ("m2" and the superscript form must land in the same bucket). An empty count
 * unit defaults to "pcs"; every other empty unit is left blank (rendered as a
 * plain dash by the panel).
 */
export function normalizeUnit(unit: string | null | undefined, kind: string): string {
  const u = (unit ?? '').trim();
  if (!u) return kind === 'count' ? 'pcs' : '';
  // Fold the superscript area / volume marks to ASCII digits so "m2" and the
  // superscript form ("m" + U+00B2) collapse into a single grouping bucket.
  const sup2 = String.fromCharCode(0xb2);
  const sup3 = String.fromCharCode(0xb3);
  return u.split(sup2).join('2').split(sup3).join('3');
}

/**
 * Pick a readable trade / classification label for a BOQ position. Prefers a
 * known classification standard, then any classification value, and falls back
 * to the owning BOQ's name so a row is never unlabelled.
 */
export function classificationLabel(
  classification: Record<string, string> | null | undefined,
  fallback: string,
): string {
  if (classification) {
    for (const std of ['din276', 'nrm', 'masterformat', 'uniclass', 'omniclass']) {
      const v = classification[std];
      if (v && v.trim()) return `${std.toUpperCase()} ${v.trim()}`;
    }
    for (const key of Object.keys(classification)) {
      const v = classification[key];
      if (v && String(v).trim()) return String(v).trim();
    }
  }
  return fallback;
}

/* ── Source mappers ──────────────────────────────────────────────────── */

/**
 * Map takeoff measurements into normalized quantity records.
 *
 * Annotation markups (cloud / arrow / text / rectangle / highlight) carry no
 * numeric value and are skipped. A deduction (opening / void) is stored
 * negative so a group nets gross minus openings, matching the ledger + export.
 */
export function measurementsToRecords(measurements: MeasurementResponse[]): QuantityRecord[] {
  const out: QuantityRecord[] = [];
  for (const m of measurements) {
    const raw = m.measurement_value ?? m.count_value;
    if (raw === null || raw === undefined) continue; // annotation, no quantity
    let value = toNum(raw);
    if (m.is_deduction) value = -Math.abs(value);
    const trade = (m.group_name ?? '').trim() || 'General';
    out.push({
      source: 'takeoff',
      unit: normalizeUnit(m.measurement_unit, m.type),
      trade,
      kind: m.type,
      value,
      label: (m.annotation ?? '').trim() || trade,
      documentId: m.document_id ?? null,
    });
  }
  return out;
}

/**
 * Map BOQ positions into normalized quantity records. Section headers (a
 * position with no unit) are skipped, as are lines whose quantity is still 0
 * (not measured yet), so the rollup reflects real measured quantities.
 */
export function boqsToRecords(boqs: BoqPositions[]): QuantityRecord[] {
  const out: QuantityRecord[] = [];
  for (const boq of boqs) {
    const fallback = (boq.name ?? '').trim() || 'BOQ';
    for (const p of boq.positions) {
      if (isSection(p)) continue;
      const value = toNum(p.quantity);
      if (value === 0) continue; // unmeasured line
      out.push({
        source: 'boq',
        unit: normalizeUnit(p.unit, 'boq_line'),
        trade: classificationLabel(p.classification, fallback),
        kind: 'boq_line',
        value,
        label: (p.description ?? '').trim() || p.ordinal || fallback,
        documentId: null,
      });
    }
  }
  return out;
}

/* ── Aggregation ─────────────────────────────────────────────────────── */

function groupValue(record: QuantityRecord, dimension: RollupDimension): string {
  if (dimension === 'unit') return record.unit || NO_UNIT;
  if (dimension === 'trade') return record.trade || 'General';
  if (dimension === 'source') return record.source;
  return record.kind;
}

/**
 * Aggregate records into (group, unit) buckets for the chosen dimension.
 * Rows are sorted by group, then by descending total, then by unit.
 */
export function aggregateRecords(
  records: QuantityRecord[],
  dimension: RollupDimension,
): RollupRow[] {
  const map = new Map<string, RollupRow>();
  for (const r of records) {
    const group = groupValue(r, dimension);
    const unit = r.unit || NO_UNIT;
    const key = JSON.stringify([group, unit]);
    const existing = map.get(key);
    if (existing) {
      existing.count += 1;
      existing.total += r.value;
      if (!existing.sources.includes(r.source)) existing.sources.push(r.source);
    } else {
      map.set(key, { group, unit, count: 1, total: r.value, sources: [r.source] });
    }
  }
  return Array.from(map.values()).sort(
    (a, b) =>
      a.group.localeCompare(b.group) ||
      b.total - a.total ||
      a.unit.localeCompare(b.unit),
  );
}

/** Per-unit grand totals across every record (unit is the only safe sum key). */
export function totalsByUnit(records: QuantityRecord[]): UnitTotal[] {
  const map = new Map<string, UnitTotal>();
  for (const r of records) {
    const unit = r.unit || NO_UNIT;
    const existing = map.get(unit);
    if (existing) {
      existing.count += 1;
      existing.total += r.value;
      if (!existing.sources.includes(r.source)) existing.sources.push(r.source);
    } else {
      map.set(unit, { unit, count: 1, total: r.value, sources: [r.source] });
    }
  }
  return Array.from(map.values()).sort(
    (a, b) => b.count - a.count || a.unit.localeCompare(b.unit),
  );
}

/** Group aggregated rows by their group value, preserving row order. */
export function groupRows(rows: RollupRow[]): Array<{ group: string; rows: RollupRow[] }> {
  const order: string[] = [];
  const byGroup = new Map<string, RollupRow[]>();
  for (const row of rows) {
    const list = byGroup.get(row.group);
    if (list) {
      list.push(row);
    } else {
      byGroup.set(row.group, [row]);
      order.push(row.group);
    }
  }
  return order.map((group) => ({ group, rows: byGroup.get(group) ?? [] }));
}

/** Distinct, sorted values for a record selector (drives the filter dropdowns). */
export function distinctValues(
  records: QuantityRecord[],
  selector: (r: QuantityRecord) => string,
): string[] {
  const set = new Set<string>();
  for (const r of records) {
    const v = selector(r);
    if (v) set.add(v);
  }
  return Array.from(set).sort((a, b) => a.localeCompare(b));
}

/* ── CSV export (mirrors the resource-summary buy-list pattern) ──────── */

/** Escape one CSV cell: quote when it holds a comma / quote / newline / semicolon. */
function csvCell(value: string | number | null | undefined): string {
  const s = value === null || value === undefined ? '' : String(value);
  return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Column headers for the exported CSV (pre-translated at the call site). */
export interface QuantitiesCsvHeaders {
  group: string;
  unit: string;
  count: string;
  total: string;
  sources: string;
}

/**
 * Build a spreadsheet-friendly CSV from aggregated rows. Totals are written in
 * canonical (stored) units so the export stays portable regardless of the
 * viewer's metric / imperial display preference. Rows use CRLF for maximal
 * spreadsheet compatibility.
 */
export function buildQuantitiesCsv(rows: RollupRow[], headers: QuantitiesCsvHeaders): string {
  const lines: string[] = [];
  lines.push(
    [headers.group, headers.unit, headers.count, headers.total, headers.sources]
      .map(csvCell)
      .join(','),
  );
  for (const r of rows) {
    lines.push(
      [r.group, r.unit, r.count, Number(r.total.toFixed(4)), r.sources.join(' + ')]
        .map(csvCell)
        .join(','),
    );
  }
  return lines.join('\r\n');
}

/**
 * Trigger a client-side download for a CSV string. A UTF-8 BOM is prepended so
 * spreadsheets open non-ASCII trade / unit labels correctly. The BOM is
 * generated at runtime so no invisible byte lives in source.
 */
export function downloadCsv(csv: string, filename: string): void {
  const bom = String.fromCharCode(0xfeff);
  const blob = new Blob([bom, csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  // Defer revoke so the download fires under all browsers.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** Deterministic, filesystem-safe CSV filename for a project's quantities. */
export function quantitiesCsvName(projectName: string, date: Date = new Date()): string {
  const slug =
    (projectName || 'project')
      .replace(/[^\p{L}\p{N}]+/gu, '_')
      .replace(/_+/g, '_')
      .replace(/^_|_$/g, '')
      .toLowerCase() || 'project';
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, '0');
  const dd = String(date.getDate()).padStart(2, '0');
  return `quantities-${slug}-${yyyy}-${mm}-${dd}.csv`;
}
