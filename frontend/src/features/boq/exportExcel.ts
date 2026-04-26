/**
 * BOQ → Excel export.
 *
 * Migrated from `xlsx` (SheetJS — unfixable HIGH npm audit advisories
 * GHSA-4r6h-8v6p-xvw6 / GHSA-5pgg-2g8v-p4x9) to `exceljs`.  ExcelJS is
 * heavy (~1MB), so the dependency is pulled in via a dynamic `import()`
 * inside the export entry-point.  Importing this module is cheap; it
 * only becomes expensive once the user actually clicks "Export".
 */

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
  boqTitle: string;
  currency: string;
  positions: Position[];
  markupTotals: ExportMarkupTotal[];
  netTotal: number;
  vatRate: number;
  vatAmount: number;
  grossTotal: number;
  /** Optional project name for the header. */
  projectName?: string;
  /** Optional classification standard (e.g. "DIN 276"). */
  classificationStandard?: string;
  /** Optional region (e.g. "DACH"). */
  region?: string;
}

/* ── Helpers ──────────────────────────────────────────────────────────── */

const CURRENCY_FMT = '#,##0.00';
const QTY_FMT = '#,##0.00';

interface Resource {
  name: string;
  code?: string;
  type: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  total?: number;
}

function getResources(pos: Position): Resource[] {
  const meta = pos.metadata ?? (pos as unknown as Record<string, unknown>).metadata_;
  if (!meta || !Array.isArray((meta as Record<string, unknown>).resources)) return [];
  return (meta as Record<string, unknown>).resources as Resource[];
}

/* ── Constants ────────────────────────────────────────────────────────── */

const BOQ_COLUMNS = ['No.', 'Description', 'Unit', 'Quantity', 'Unit Rate', 'Total', 'Type', 'Code'];

/** A single 2-D table of values; null for blank cells. */
type Row = (string | number | null)[];

/** A 1-based merge range using ExcelJS coordinates. */
interface MergeRange {
  topRow: number;
  topCol: number;
  bottomRow: number;
  bottomCol: number;
}

/* ── BOQ sheet builder ────────────────────────────────────────────────── */

/**
 * Build the rows + merge ranges for the BOQ worksheet.  The result is
 * library-agnostic: the values are plain JS, the merges use 1-based
 * coordinates compatible with ExcelJS' `worksheet.mergeCells(...)`.
 */
export function buildBOQSheetData(options: ExportOptions): {
  rows: Row[];
  merges: MergeRange[];
  /** Indices (0-based) of rows that contain numeric BOQ data and should
   *  receive currency / quantity number formatting. */
  numberFormatStartRow: number;
} {
  const { positions, boqTitle, markupTotals, netTotal, vatRate, vatAmount, grossTotal } = options;
  const grouped = groupPositionsIntoSections(positions);
  const colCount = BOQ_COLUMNS.length;
  const itemCount = positions.filter((p) => !isSection(p)).length;
  const sectionCount = grouped.sections.length;
  const dateStr = new Date().toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });

  const rows: Row[] = [];
  const merges: MergeRange[] = [];

  // 0-based index helper; we convert to 1-based at merge time.
  const merge = (r0: number, c0: number, r1: number, c1: number): void => {
    merges.push({ topRow: r0 + 1, topCol: c0 + 1, bottomRow: r1 + 1, bottomCol: c1 + 1 });
  };

  // ── Header block ──────────────────────────────────────────────────────
  rows.push([`BILL OF QUANTITIES — ${boqTitle}`, ...Array(colCount - 1).fill(null)]);
  merge(0, 0, 0, colCount - 1);

  const infoLine = [
    options.projectName ? `Project: ${options.projectName}` : null,
    options.classificationStandard ? `Standard: ${options.classificationStandard}` : null,
    options.region ? `Region: ${options.region}` : null,
  ]
    .filter(Boolean)
    .join('  |  ');
  rows.push([infoLine || 'OpenConstructionERP', ...Array(colCount - 1).fill(null)]);
  merge(1, 0, 1, colCount - 1);

  const statsLine = `Date: ${dateStr}  |  ${sectionCount} sections  |  ${itemCount} positions  |  Gross Total: ${options.currency}${grossTotal.toLocaleString(
    undefined,
    { minimumFractionDigits: 2, maximumFractionDigits: 2 },
  )}`;
  rows.push([statsLine, ...Array(colCount - 1).fill(null)]);
  merge(2, 0, 2, colCount - 1);

  // Empty separator row
  rows.push(Array(colCount).fill(null));

  // Column headers (row index 4 → first data row at index 5)
  rows.push([...BOQ_COLUMNS]);
  const numberFormatStartRow = rows.length; // 0-based start for number formatting

  // ── Data rows ─────────────────────────────────────────────────────────
  for (const group of grouped.sections) {
    const sectionRowIdx = rows.length;
    rows.push([
      group.section.ordinal,
      group.section.description,
      null,
      null,
      null,
      group.subtotal,
      null,
      null,
    ]);
    merge(sectionRowIdx, 1, sectionRowIdx, 4);

    for (const child of group.children) {
      rows.push([
        child.ordinal,
        child.description,
        child.unit,
        child.quantity,
        child.unit_rate,
        child.total,
        null,
        null,
      ]);
      for (const r of getResources(child)) {
        const rTotal = r.total ?? r.quantity * r.unit_rate;
        rows.push([
          null,
          `    \u2514 ${r.name}`,
          r.unit,
          r.quantity,
          r.unit_rate,
          rTotal,
          r.type || '',
          r.code || '',
        ]);
      }
    }

    rows.push([
      null,
      `Subtotal: ${group.section.description}`,
      null,
      null,
      null,
      group.subtotal,
      null,
      null,
    ]);
    merge(rows.length - 1, 1, rows.length - 1, 4);

    rows.push(Array(colCount).fill(null));
  }

  // Ungrouped
  for (const pos of grouped.ungrouped) {
    if (isSection(pos)) continue;
    rows.push([pos.ordinal, pos.description, pos.unit, pos.quantity, pos.unit_rate, pos.total, null, null]);
    for (const r of getResources(pos)) {
      const rTotal = r.total ?? r.quantity * r.unit_rate;
      rows.push([
        null,
        `    \u2514 ${r.name}`,
        r.unit,
        r.quantity,
        r.unit_rate,
        rTotal,
        r.type || '',
        r.code || '',
      ]);
    }
  }

  // ── Summary block ─────────────────────────────────────────────────────
  rows.push(Array(colCount).fill(null));
  rows.push([null, 'COST SUMMARY', null, null, null, null, null, null]);
  merge(rows.length - 1, 1, rows.length - 1, 4);

  const directCost = positions.filter((p) => !isSection(p)).reduce((sum, p) => sum + p.total, 0);
  rows.push([null, 'Direct Cost', null, null, null, directCost, null, null]);

  for (const m of markupTotals) {
    rows.push([null, `  + ${m.name} (${m.percentage}%)`, null, null, null, m.amount, null, null]);
  }

  rows.push(Array(colCount).fill(null));
  rows.push([null, 'Net Total', null, null, null, netTotal, null, null]);

  const vatLabel = vatRate > 0 ? `VAT (${(vatRate * 100).toFixed(0)}%)` : 'VAT (0%)';
  rows.push([null, `  + ${vatLabel}`, null, null, null, vatAmount, null, null]);

  rows.push(Array(colCount).fill(null));
  rows.push([null, 'GROSS TOTAL', null, null, null, grossTotal, null, null]);
  merge(rows.length - 1, 1, rows.length - 1, 4);

  // Footer
  rows.push(Array(colCount).fill(null));
  rows.push([
    `Generated by OpenConstructionERP  |  ${dateStr}  |  openconstructionerp.com`,
    ...Array(colCount - 1).fill(null),
  ]);
  merge(rows.length - 1, 0, rows.length - 1, colCount - 1);

  return { rows, merges, numberFormatStartRow };
}

/* ── Summary sheet builder ────────────────────────────────────────────── */

export function buildSummarySheetData(options: ExportOptions): {
  rows: Row[];
  numberFormatStartRow: number;
} {
  const { positions, markupTotals, netTotal, vatRate, vatAmount, grossTotal } = options;
  const grouped = groupPositionsIntoSections(positions);
  const dateStr = new Date().toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });

  const rows: Row[] = [];
  rows.push(['COST BREAKDOWN BY SECTION', null, null]);
  rows.push([options.projectName ? `Project: ${options.projectName}` : options.boqTitle, null, null]);
  rows.push([`Date: ${dateStr}`, null, null]);
  rows.push([null, null, null]);

  rows.push(['Section', 'Positions', 'Subtotal']);
  const numberFormatStartRow = rows.length;

  for (const group of grouped.sections) {
    rows.push([
      `${group.section.ordinal}  ${group.section.description}`.trim(),
      group.children.length,
      group.subtotal,
    ]);
  }

  const ungroupedItems = grouped.ungrouped.filter((p) => !isSection(p));
  if (ungroupedItems.length > 0) {
    const ungroupedTotal = ungroupedItems.reduce((sum, p) => sum + p.total, 0);
    rows.push(['Ungrouped Items', ungroupedItems.length, ungroupedTotal]);
  }

  rows.push([null, null, null]);

  const directCost = positions.filter((p) => !isSection(p)).reduce((sum, p) => sum + p.total, 0);
  rows.push(['Direct Cost', null, directCost]);
  for (const m of markupTotals) {
    rows.push([`  + ${m.name} (${m.percentage}%)`, null, m.amount]);
  }
  rows.push(['Net Total', null, netTotal]);
  const vatLabel = vatRate > 0 ? `VAT (${(vatRate * 100).toFixed(0)}%)` : 'VAT (0%)';
  rows.push([`  + ${vatLabel}`, null, vatAmount]);
  rows.push([null, null, null]);
  rows.push(['GROSS TOTAL', null, grossTotal]);

  return { rows, numberFormatStartRow };
}

/* ── Build & download ─────────────────────────────────────────────────── */

/** Build the workbook as a binary buffer (does NOT touch the DOM).  Used
 *  by tests and by the download path. */
export async function buildBOQWorkbookBuffer(options: ExportOptions): Promise<ArrayBuffer> {
  // Lazy-load ExcelJS; ~1MB module that we never want in the main bundle.
  const ExcelJS = (await import('exceljs')).default;
  const wb = new ExcelJS.Workbook();
  wb.creator = 'OpenConstructionERP — DataDrivenConstruction';
  wb.company = 'DataDrivenConstruction (DDC)';
  wb.created = new Date();
  // ExcelJS exposes only a small set of standard properties; stuff the
  // application identity into `keywords` so the marker survives a
  // round-trip via `xlsx`-compatible readers.
  wb.keywords = 'DDC-CWICR-OE/1.5';

  // ── BOQ sheet ─────────────────────────────────────────────────────────
  const boqSheet = wb.addWorksheet('BOQ');
  const { rows: boqRows, merges, numberFormatStartRow } = buildBOQSheetData(options);

  for (const row of boqRows) {
    boqSheet.addRow(row);
  }

  for (const m of merges) {
    boqSheet.mergeCells(m.topRow, m.topCol, m.bottomRow, m.bottomCol);
  }

  boqSheet.columns = [
    { width: 12 }, // No.
    { width: 50 }, // Description
    { width: 8 }, // Unit
    { width: 14 }, // Quantity
    { width: 14 }, // Unit Rate
    { width: 16 }, // Total
    { width: 12 }, // Type
    { width: 14 }, // Code
  ];

  // Number format for quantity / unit rate / total columns (1-based: 4, 5, 6)
  for (let r = numberFormatStartRow + 1; r <= boqSheet.rowCount; r++) {
    const row = boqSheet.getRow(r);
    for (const c of [4, 5, 6]) {
      const cell = row.getCell(c);
      if (typeof cell.value === 'number') {
        cell.numFmt = c === 4 ? QTY_FMT : CURRENCY_FMT;
      }
    }
  }

  // ── Summary sheet ─────────────────────────────────────────────────────
  const summarySheet = wb.addWorksheet('Summary');
  const { rows: sumRows, numberFormatStartRow: sumNumStart } = buildSummarySheetData(options);
  for (const row of sumRows) {
    summarySheet.addRow(row);
  }
  summarySheet.columns = [{ width: 45 }, { width: 12 }, { width: 18 }];

  for (let r = sumNumStart + 1; r <= summarySheet.rowCount; r++) {
    const row = summarySheet.getRow(r);
    const cell = row.getCell(3);
    if (typeof cell.value === 'number') {
      cell.numFmt = CURRENCY_FMT;
    }
  }

  return await wb.xlsx.writeBuffer();
}

/* ── Main export function ─────────────────────────────────────────────── */

export async function exportBOQToExcel(options: ExportOptions): Promise<void> {
  const buf = await buildBOQWorkbookBuffer(options);

  const safeName = options.boqTitle.replace(/[^a-zA-Z0-9_\- ]/g, '').trim() || 'BOQ';
  const filename = `${safeName}.xlsx`;

  const blob = new Blob([buf], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Defer revoke to next tick so Safari has a chance to start the download.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
