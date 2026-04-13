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

/* ── Build BOQ worksheet ──────────────────────────────────────────────── */

const BOQ_COLUMNS = ['No.', 'Description', 'Unit', 'Quantity', 'Unit Rate', 'Total', 'Type', 'Code'];

export function buildBOQSheet(options: ExportOptions): {
  ws: XLSX.WorkSheet;
  merges: XLSX.Range[];
} {
  const { positions, boqTitle, markupTotals, netTotal, vatRate, vatAmount, grossTotal } = options;
  const grouped = groupPositionsIntoSections(positions);
  const colCount = BOQ_COLUMNS.length;
  const itemCount = positions.filter((p) => !isSection(p)).length;
  const sectionCount = grouped.sections.length;
  const dateStr = new Date().toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });

  const rows: (string | number | null)[][] = [];
  const merges: XLSX.Range[] = [];

  // ── Header block ──────────────────────────────────────────────────────
  // Row 0: Title
  rows.push([`BILL OF QUANTITIES — ${boqTitle}`, ...Array(colCount - 1).fill(null)]);
  merges.push({ s: { r: 0, c: 0 }, e: { r: 0, c: colCount - 1 } });

  // Row 1: Project info line
  const infoLine = [
    options.projectName ? `Project: ${options.projectName}` : null,
    options.classificationStandard ? `Standard: ${options.classificationStandard}` : null,
    options.region ? `Region: ${options.region}` : null,
  ].filter(Boolean).join('  |  ');
  rows.push([infoLine || 'OpenConstructionERP', ...Array(colCount - 1).fill(null)]);
  merges.push({ s: { r: 1, c: 0 }, e: { r: 1, c: colCount - 1 } });

  // Row 2: Date + stats
  const statsLine = `Date: ${dateStr}  |  ${sectionCount} sections  |  ${itemCount} positions  |  Gross Total: ${options.currency}${grossTotal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  rows.push([statsLine, ...Array(colCount - 1).fill(null)]);
  merges.push({ s: { r: 2, c: 0 }, e: { r: 2, c: colCount - 1 } });

  // Row 3: Empty separator
  rows.push(Array(colCount).fill(null));

  // Row 4: Column headers
  rows.push([...BOQ_COLUMNS]);

  // ── Data rows ─────────────────────────────────────────────────────────
  for (const group of grouped.sections) {
    const sectionRowIdx = rows.length;
    // Section header row
    rows.push([
      group.section.ordinal,
      group.section.description,
      null, null, null,
      group.subtotal,
      null, null,
    ]);
    merges.push({ s: { r: sectionRowIdx, c: 1 }, e: { r: sectionRowIdx, c: 4 } });

    // Positions
    for (const child of group.children) {
      rows.push([
        child.ordinal,
        child.description,
        child.unit,
        child.quantity,
        child.unit_rate,
        child.total,
        null, null,
      ]);
      // Resources
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

    // Section subtotal row
    rows.push([null, `Subtotal: ${group.section.description}`, null, null, null, group.subtotal, null, null]);
    merges.push({ s: { r: rows.length - 1, c: 1 }, e: { r: rows.length - 1, c: 4 } });

    // Section separator
    rows.push(Array(colCount).fill(null));
  }

  // Ungrouped
  for (const pos of grouped.ungrouped) {
    if (isSection(pos)) continue;
    rows.push([pos.ordinal, pos.description, pos.unit, pos.quantity, pos.unit_rate, pos.total, null, null]);
    for (const r of getResources(pos)) {
      const rTotal = r.total ?? r.quantity * r.unit_rate;
      rows.push([null, `    \u2514 ${r.name}`, r.unit, r.quantity, r.unit_rate, rTotal, r.type || '', r.code || '']);
    }
  }

  // ── Summary block ─────────────────────────────────────────────────────
  rows.push(Array(colCount).fill(null));
  rows.push([null, 'COST SUMMARY', null, null, null, null, null, null]);
  merges.push({ s: { r: rows.length - 1, c: 1 }, e: { r: rows.length - 1, c: 4 } });

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
  merges.push({ s: { r: rows.length - 1, c: 1 }, e: { r: rows.length - 1, c: 4 } });

  // ── Footer ────────────────────────────────────────────────────────────
  rows.push(Array(colCount).fill(null));
  rows.push([`Generated by OpenConstructionERP  |  ${dateStr}  |  openconstructionerp.com`, ...Array(colCount - 1).fill(null)]);
  merges.push({ s: { r: rows.length - 1, c: 0 }, e: { r: rows.length - 1, c: colCount - 1 } });

  // ── Build worksheet ───────────────────────────────────────────────────
  const ws = XLSX.utils.aoa_to_sheet(rows);
  ws['!cols'] = [
    { wch: 12 },  // No.
    { wch: 50 },  // Description
    { wch: 8 },   // Unit
    { wch: 14 },  // Quantity
    { wch: 14 },  // Unit Rate
    { wch: 16 },  // Total
    { wch: 12 },  // Type
    { wch: 14 },  // Code
  ];
  ws['!merges'] = merges;

  // Number format
  for (let r = 4; r < rows.length; r++) {
    for (const c of [3, 4, 5]) {
      const cell = XLSX.utils.encode_cell({ r, c });
      if (ws[cell] && typeof ws[cell].v === 'number') {
        ws[cell].z = c === 3 ? '#,##0.00' : CURRENCY_FMT;
      }
    }
  }

  return { ws, merges };
}

/* ── Build Summary worksheet ──────────────────────────────────────────── */

export function buildSummarySheet(options: ExportOptions): XLSX.WorkSheet {
  const { positions, markupTotals, netTotal, vatRate, vatAmount, grossTotal } = options;
  const grouped = groupPositionsIntoSections(positions);
  const dateStr = new Date().toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });

  const rows: (string | number | null)[][] = [];

  // Header
  rows.push(['COST BREAKDOWN BY SECTION', null, null]);
  rows.push([options.projectName ? `Project: ${options.projectName}` : options.boqTitle, null, null]);
  rows.push([`Date: ${dateStr}`, null, null]);
  rows.push([null, null, null]);

  // Column headers
  rows.push(['Section', 'Positions', 'Subtotal']);

  // Section subtotals
  for (const group of grouped.sections) {
    rows.push([
      `${group.section.ordinal}  ${group.section.description}`.trim(),
      group.children.length,
      group.subtotal,
    ]);
  }

  // Ungrouped
  const ungroupedItems = grouped.ungrouped.filter((p) => !isSection(p));
  if (ungroupedItems.length > 0) {
    const ungroupedTotal = ungroupedItems.reduce((sum, p) => sum + p.total, 0);
    rows.push(['Ungrouped Items', ungroupedItems.length, ungroupedTotal]);
  }

  rows.push([null, null, null]);

  // Summary
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

  const ws = XLSX.utils.aoa_to_sheet(rows);
  ws['!cols'] = [{ wch: 45 }, { wch: 12 }, { wch: 18 }];

  // Number format
  for (let r = 4; r < rows.length; r++) {
    const cell2 = XLSX.utils.encode_cell({ r, c: 2 });
    if (ws[cell2] && typeof ws[cell2].v === 'number') {
      ws[cell2].z = CURRENCY_FMT;
    }
  }

  return ws;
}

/* ── Main export function ─────────────────────────────────────────────── */

export function exportBOQToExcel(options: ExportOptions): void {
  const wb = XLSX.utils.book_new();
  // Workbook metadata — DDC identity marker
  wb.Props = {
    Author: 'OpenConstructionERP — DataDrivenConstruction',
    Company: 'DataDrivenConstruction (DDC)',
    Application: 'DDC-CWICR-OE/1.5',
    CreatedDate: new Date(),
  };

  const { ws: boqSheet } = buildBOQSheet(options);
  XLSX.utils.book_append_sheet(wb, boqSheet, 'BOQ');

  const summarySheet = buildSummarySheet(options);
  XLSX.utils.book_append_sheet(wb, summarySheet, 'Summary');

  const safeName = options.boqTitle.replace(/[^a-zA-Z0-9_\- ]/g, '').trim() || 'BOQ';
  const filename = `${safeName}.xlsx`;

  XLSX.writeFile(wb, filename);
}
