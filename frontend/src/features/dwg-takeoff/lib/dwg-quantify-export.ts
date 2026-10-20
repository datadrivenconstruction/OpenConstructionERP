// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Client-side Excel export for the DWG auto-quantify table.
 *
 * Turns the per-layer vector quantities (and the count-by-block rollup) into
 * a downloadable .xlsx so estimators can hand the takeoff straight to a
 * spreadsheet without retyping. exceljs is imported lazily (≈1 MB) so it
 * never weighs down the main bundle - only when the user clicks Export.
 *
 * Mirrors the established pattern in ``features/takeoff/lib/takeoff-export.ts``
 * (lazy ctor resolve + ``neutraliseFormula`` defence + blob download).
 */

import type * as ExcelJS from 'exceljs';
import type { LayerQuantity } from './auto-quantify';
import { quantifyTotals, type QuantifyTotals } from './takeoff-totals';
import {
  toDisplayQuantity,
  displayUnitFor,
} from '@/shared/lib/unitConversion';
import type { MeasurementSystem } from '@/stores/usePreferencesStore';

const HEADER_FILL = 'FF1F2937';

/**
 * Defuse spreadsheet-formula injection: any cell text starting with a
 * formula trigger (``= + - @`` or a control char) is prefixed with an
 * apostrophe so Excel/Sheets treats it as literal text. Mirrors the backend
 * and BOQ-export guards (OWASP CSV-injection defence).
 */
export function neutraliseFormula(value: string): string {
  if (value && /^[=+\-@\t\r\n]/.test(value)) return `'${value}`;
  return value;
}

/** Standard blob → ``<a download>`` trigger with deferred URL revoke. */
export function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export interface QuantifyExportContext {
  /** Drawing name, used for the sheet header + filename. */
  drawingName: string;
  /** Per-layer auto-quantify rows (from ``quantifyByLayer``). */
  layerQuantities: LayerQuantity[];
  /** Drawing totals the UI shows (``quantifyTotals``). Recomputed from
   *  ``layerQuantities`` when omitted, never from a different rule. */
  totals?: QuantifyTotals;
  /** Manual Distance / Area / Count annotations, real-world values. */
  manualRows?: { type: string; text: string; value: number; unit: string }[];
  /** Count-by-block rollup (INSERT entities), optional. */
  byBlock?: { name: string; count: number }[];
  /** Manual count-tool tally, optional. */
  countTotal?: number;
  /**
   * Display measurement system for the WRITTEN sheet. Storage stays
   * metric-canonical; this only relabels the column headers (m -> ft) and
   * scales the rendered values. Defaults to ``metric`` (byte-identical to
   * the historical output) when the caller does not pass a preference.
   */
  measurementSystem?: MeasurementSystem;
  /** Override-able for deterministic tests. */
  exportDate?: Date;
}

function styleHeader(row: ExcelJS.Row): void {
  row.font = { bold: true, color: { argb: 'FFFFFFFF' } };
  row.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: HEADER_FILL } };
  row.alignment = { vertical: 'middle' };
}

/**
 * Build a workbook with a "Quantities by layer" sheet (+ a "Count by block"
 * sheet when the drawing has block references).
 */
export async function buildQuantifyWorkbook(
  ctx: QuantifyExportContext,
): Promise<ExcelJS.Workbook> {
  const mod = await import('exceljs');
  const Ctor = (mod.Workbook ?? mod.default.Workbook) as typeof ExcelJS.Workbook;
  const wb = new Ctor();
  wb.creator = 'OpenConstructionERP';
  wb.created = ctx.exportDate ?? new Date();

  // Display measurement system for this written sheet. Storage is always
  // metric-canonical; everything below only converts at the export boundary
  // (header labels + the numeric values), never the source rows.
  const system: MeasurementSystem = ctx.measurementSystem ?? 'metric';
  const round3 = (n: number) => Math.round(n * 1000) / 1000;
  // Convert + round a canonical metric value for the sheet. Returns the
  // empty string for non-positive inputs so blank cells stay blank.
  const conv = (value: number, metricUnit: string): number | '' =>
    value > 0 ? round3(toDisplayQuantity(value, metricUnit, system).value) : '';

  /* ── Quantities by layer ─────────────────────────────────────── */
  const ws = wb.addWorksheet('Quantities by layer');
  ws.columns = [
    { header: 'Layer', key: 'layer', width: 26 },
    { header: 'Measure', key: 'measure', width: 12 },
    { header: 'Quantity', key: 'quantity', width: 14 },
    { header: 'Unit', key: 'unit', width: 8 },
    { header: `Area (${displayUnitFor('m²', system)})`, key: 'area', width: 12 },
    { header: `Length (${displayUnitFor('m', system)})`, key: 'length', width: 12 },
    { header: 'Entities', key: 'entities', width: 10 },
  ];
  styleHeader(ws.getRow(1));

  const totals = ctx.totals ?? quantifyTotals(ctx.layerQuantities);
  for (const row of ctx.layerQuantities) {
    // The per-row headline quantity carries its own unit ("m²"/"m"/"nr");
    // "nr" has no imperial mapping so it passes through unchanged.
    const q = toDisplayQuantity(row.quantity, row.unit, system);
    ws.addRow({
      layer: neutraliseFormula(row.layer),
      measure: row.primary,
      quantity: round3(q.value),
      unit: q.unit,
      area: conv(row.area, 'm²'),
      length: conv(row.length, 'm'),
      entities: row.count,
    });
  }

  const totalRow = ws.addRow({
    layer: 'TOTAL',
    measure: '',
    quantity: '',
    unit: '',
    area: round3(toDisplayQuantity(totals.area, 'm²', system).value),
    length: round3(toDisplayQuantity(totals.length, 'm', system).value),
    entities: totals.count,
  });
  totalRow.font = { bold: true };
  totalRow.border = { top: { style: 'thin' } };

  if (ctx.countTotal && ctx.countTotal > 0) {
    const cRow = ws.addRow({ layer: 'Manual count items', measure: '', quantity: ctx.countTotal, unit: 'nr' });
    cRow.font = { italic: true };
  }

  /* ── Manual measurements ─────────────────────────────────────── */
  if (ctx.manualRows && ctx.manualRows.length > 0) {
    const wsM = wb.addWorksheet('Manual measurements');
    wsM.columns = [
      { header: 'Type', key: 'type', width: 12 },
      { header: 'Label', key: 'label', width: 30 },
      { header: 'Quantity', key: 'quantity', width: 14 },
      { header: 'Unit', key: 'unit', width: 8 },
    ];
    styleHeader(wsM.getRow(1));
    for (const r of ctx.manualRows) {
      const metricUnit = r.type === 'count' ? 'nr' : r.unit.includes('²') ? 'm²' : 'm';
      const q = toDisplayQuantity(r.value, metricUnit, system);
      wsM.addRow({
        type: r.type,
        label: neutraliseFormula(r.text),
        quantity: round3(q.value),
        unit: q.unit,
      });
    }
  }

  /* ── Count by block ──────────────────────────────────────────── */
  if (ctx.byBlock && ctx.byBlock.length > 0) {
    const wsB = wb.addWorksheet('Count by block');
    wsB.columns = [
      { header: 'Block', key: 'block', width: 30 },
      { header: 'Count', key: 'count', width: 10 },
    ];
    styleHeader(wsB.getRow(1));
    let total = 0;
    for (const b of ctx.byBlock) {
      total += b.count;
      wsB.addRow({ block: neutraliseFormula(b.name), count: b.count });
    }
    const tRow = wsB.addRow({ block: 'TOTAL', count: total });
    tRow.font = { bold: true };
    tRow.border = { top: { style: 'thin' } };
  }

  return wb;
}

/** Build + download the quantify workbook as ``dwg-quantities-<name>.xlsx``. */
export async function exportQuantifyToExcel(ctx: QuantifyExportContext): Promise<void> {
  const wb = await buildQuantifyWorkbook(ctx);
  const buf = await wb.xlsx.writeBuffer();
  const blob = new Blob([buf], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  const slug =
    (ctx.drawingName || 'drawing')
      .replace(/[^\p{L}\p{N}]+/gu, '_')
      .replace(/_+/g, '_')
      .replace(/^_|_$/g, '')
      .toLowerCase() || 'drawing';
  triggerDownload(blob, `dwg-quantities-${slug}.xlsx`);
}
