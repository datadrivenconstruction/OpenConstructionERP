import * as XLSX from 'xlsx';
import {
  groupPositionsIntoSections,
  isSection,
  type Position,
} from './api';

/* ── Types ────────────────────────────────────────────────────────────── */

export interface ExportMarkupTotal {
  name: string;
  percentage: number;
  amount: number;
}

export interface ExportOptions {
  /** BOQ title shown in the header row of the spreadsheet. */
  boqTitle: string;
  /** Currency symbol to prepend in display (e.g. "€", "$"). */
  currency: string;
  /** Flat list of all BOQ positions (sections + items). */
  positions: Position[];
  /** Applied markups with pre-computed amounts. */
  markupTotals: ExportMarkupTotal[];
  /** Net total after markups. */
  netTotal: number;
  /** VAT rate as decimal (e.g. 0.19 for 19%). */
  vatRate: number;
  /** VAT amount (pre-computed). */
  vatAmount: number;
  /** Gross total including VAT (pre-computed). */
  grossTotal: number;
}

/* ── Column definitions ───────────────────────────────────────────────── */

const BOQ_COLUMNS = ['Ordinal', 'Description', 'Unit', 'Quantity', 'Unit Rate', 'Total'];
const SUMMARY_COLUMNS = ['Section', 'Subtotal'];

/* ── Helpers ──────────────────────────────────────────────────────────── */

/** Auto-fit column widths based on content length. */
function computeColumnWidths(rows: (string | number | null | undefined)[][]): XLSX.ColInfo[] {
  const widths: number[] = [];
  for (const row of rows) {
    for (let i = 0; i < row.length; i++) {
      const cellLen = String(row[i] ?? '').length;
      widths[i] = Math.max(widths[i] ?? 0, cellLen);
    }
  }
  // Minimum width of 10, maximum of 60
  return widths.map((w) => ({ wch: Math.min(Math.max(w + 2, 10), 60) }));
}

/** Number format string for currency columns. */
const CURRENCY_FMT = '#,##0.00';

/* ── Build BOQ worksheet ──────────────────────────────────────────────── */

export function buildBOQSheet(options: ExportOptions): {
  ws: XLSX.WorkSheet;
  merges: XLSX.Range[];
} {
  const { positions, boqTitle, markupTotals, netTotal, vatRate, vatAmount, grossTotal } = options;
  const grouped = groupPositionsIntoSections(positions);

  const rows: (string | number | null)[][] = [];
  const merges: XLSX.Range[] = [];
  const sectionRowIndices: number[] = [];
  const headerRowIndices: number[] = [];
  const summaryRowIndices: number[] = [];

  // Title row
  rows.push([boqTitle, null, null, null, null, null]);
  merges.push({ s: { r: 0, c: 0 }, e: { r: 0, c: 5 } });

  // Empty separator row
  rows.push([null, null, null, null, null, null]);

  // Header row
  headerRowIndices.push(rows.length);
  rows.push([...BOQ_COLUMNS]);

  // Sections with children
  for (const group of grouped.sections) {
    const sectionRowIdx = rows.length;
    sectionRowIndices.push(sectionRowIdx);
    // Section header — merged across all columns
    rows.push([
      group.section.ordinal,
      group.section.description,
      null,
      null,
      null,
      group.subtotal,
    ]);
    merges.push({ s: { r: sectionRowIdx, c: 1 }, e: { r: sectionRowIdx, c: 4 } });

    for (const child of group.children) {
      rows.push([
        child.ordinal,
        child.description,
        child.unit,
        child.quantity,
        child.unit_rate,
        child.total,
      ]);
    }
  }

  // Ungrouped positions
  for (const pos of grouped.ungrouped) {
    if (isSection(pos)) continue;
    rows.push([pos.ordinal, pos.description, pos.unit, pos.quantity, pos.unit_rate, pos.total]);
  }

  // Empty separator
  rows.push([null, null, null, null, null, null]);

  // Summary: Direct Cost
  const directCost = positions
    .filter((p) => !isSection(p))
    .reduce((sum, p) => sum + p.total, 0);
  summaryRowIndices.push(rows.length);
  rows.push([null, 'Direct Cost', null, null, null, directCost]);

  // Markup lines
  for (const m of markupTotals) {
    summaryRowIndices.push(rows.length);
    rows.push([null, `${m.name} (${m.percentage}%)`, null, null, null, m.amount]);
  }

  // Net Total
  summaryRowIndices.push(rows.length);
  rows.push([null, 'Net Total', null, null, null, netTotal]);

  // VAT
  summaryRowIndices.push(rows.length);
  const vatLabel = vatRate > 0 ? `VAT (${(vatRate * 100).toFixed(0)}%)` : 'VAT (0%)';
  rows.push([null, vatLabel, null, null, null, vatAmount]);

  // Gross Total
  summaryRowIndices.push(rows.length);
  rows.push([null, 'Gross Total', null, null, null, grossTotal]);

  // Build worksheet
  const ws = XLSX.utils.aoa_to_sheet(rows);

  // Column widths
  ws['!cols'] = computeColumnWidths(rows);

  // Merges
  ws['!merges'] = merges;

  // Apply number format to currency columns (Unit Rate = col 4, Total = col 5)
  for (let r = 2; r < rows.length; r++) {
    const rateCell = XLSX.utils.encode_cell({ r, c: 4 });
    const totalCell = XLSX.utils.encode_cell({ r, c: 5 });
    if (ws[rateCell] && typeof ws[rateCell].v === 'number') {
      ws[rateCell].z = CURRENCY_FMT;
    }
    if (ws[totalCell] && typeof ws[totalCell].v === 'number') {
      ws[totalCell].z = CURRENCY_FMT;
    }
  }

  // Apply number format to quantity column (col 3)
  for (let r = 3; r < rows.length; r++) {
    const qtyCell = XLSX.utils.encode_cell({ r, c: 3 });
    if (ws[qtyCell] && typeof ws[qtyCell].v === 'number') {
      ws[qtyCell].z = '#,##0.00';
    }
  }

  return { ws, merges };
}

/* ── Build Summary worksheet ──────────────────────────────────────────── */

export function buildSummarySheet(options: ExportOptions): XLSX.WorkSheet {
  const { positions, markupTotals, netTotal, vatRate, vatAmount, grossTotal } = options;
  const grouped = groupPositionsIntoSections(positions);

  const rows: (string | number | null)[][] = [];

  // Header
  rows.push([...SUMMARY_COLUMNS]);

  // Section subtotals
  for (const group of grouped.sections) {
    rows.push([
      `${group.section.ordinal} ${group.section.description}`.trim(),
      group.subtotal,
    ]);
  }

  // Ungrouped total (if any non-section ungrouped positions exist)
  const ungroupedItems = grouped.ungrouped.filter((p) => !isSection(p));
  if (ungroupedItems.length > 0) {
    const ungroupedTotal = ungroupedItems.reduce((sum, p) => sum + p.total, 0);
    rows.push(['Ungrouped', ungroupedTotal]);
  }

  // Separator
  rows.push([null, null]);

  // Direct Cost
  const directCost = positions
    .filter((p) => !isSection(p))
    .reduce((sum, p) => sum + p.total, 0);
  rows.push(['Direct Cost', directCost]);

  // Markups
  for (const m of markupTotals) {
    rows.push([`${m.name} (${m.percentage}%)`, m.amount]);
  }

  // Net Total
  rows.push(['Net Total', netTotal]);

  // VAT
  const vatLabel = vatRate > 0 ? `VAT (${(vatRate * 100).toFixed(0)}%)` : 'VAT (0%)';
  rows.push([vatLabel, vatAmount]);

  // Gross Total
  rows.push(['Gross Total', grossTotal]);

  const ws = XLSX.utils.aoa_to_sheet(rows);

  // Column widths
  ws['!cols'] = computeColumnWidths(rows);

  // Number format for subtotal column
  for (let r = 1; r < rows.length; r++) {
    const cell = XLSX.utils.encode_cell({ r, c: 1 });
    if (ws[cell] && typeof ws[cell].v === 'number') {
      ws[cell].z = CURRENCY_FMT;
    }
  }

  return ws;
}

/* ── Main export function ─────────────────────────────────────────────── */

/**
 * Exports the current BOQ to an Excel (.xlsx) file and triggers a download.
 *
 * Sheet 1 ("BOQ"): all positions with columns Ordinal, Description, Unit,
 * Quantity, Unit Rate, Total. Section headers appear as merged rows.
 * Summary rows at the bottom: Direct Cost, Markups, Net Total, VAT, Gross Total.
 *
 * Sheet 2 ("Summary"): cost breakdown by section with subtotals.
 */
export function exportBOQToExcel(options: ExportOptions): void {
  const wb = XLSX.utils.book_new();

  // Sheet 1: BOQ
  const { ws: boqSheet } = buildBOQSheet(options);
  XLSX.utils.book_append_sheet(wb, boqSheet, 'BOQ');

  // Sheet 2: Summary
  const summarySheet = buildSummarySheet(options);
  XLSX.utils.book_append_sheet(wb, summarySheet, 'Summary');

  // Generate filename
  const safeName = options.boqTitle.replace(/[^a-zA-Z0-9_\- ]/g, '').trim() || 'BOQ';
  const filename = `${safeName}.xlsx`;

  // Trigger download
  XLSX.writeFile(wb, filename);
}
