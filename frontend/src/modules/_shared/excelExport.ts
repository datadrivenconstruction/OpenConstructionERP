/**
 * Shared Excel/CSV BOQ export utilities.
 *
 * Generates downloadable spreadsheet files from BOQ positions.
 * Uses native CSV generation (no external dependency).
 */

import { triggerDownload } from '@/shared/lib/api';
import type { ExchangePosition, CountryTemplate, ExportResult } from './templateTypes';

/** Escape a CSV cell value. */
function escapeCSV(val: string): string {
  if (val.includes(',') || val.includes('"') || val.includes('\n') || val.includes(';')) {
    return `"${val.replace(/"/g, '""')}"`;
  }
  return val;
}

/** Generate CSV content from positions using a country template. */
export function generateCSV(
  positions: ExchangePosition[],
  template: CountryTemplate,
  options?: { includePrices?: boolean; separator?: ',' | ';' | '\t' },
): string {
  const sep = options?.separator ?? ',';
  const includePrices = options?.includePrices ?? true;

  // Header row
  const headers = ['No.', 'Description', 'Unit', 'Quantity'];
  if (includePrices) headers.push('Unit Rate', 'Total');
  if (template.classification) headers.push(template.classification);
  if (positions.some((p) => p.section)) headers.push('Section');

  const lines: string[] = [headers.map(escapeCSV).join(sep)];

  for (const pos of positions) {
    if (pos.isSection) {
      lines.push([escapeCSV(pos.ordinal), escapeCSV(`** ${pos.description} **`), '', '', ...(includePrices ? ['', ''] : [])].join(sep));
      continue;
    }
    const row = [
      escapeCSV(pos.ordinal),
      escapeCSV(pos.description),
      escapeCSV(pos.unit),
      pos.quantity.toFixed(3),
    ];
    if (includePrices) {
      row.push(pos.unitRate.toFixed(2), pos.total.toFixed(2));
    }
    if (template.classification && pos.classification) {
      const code = Object.values(pos.classification)[0] ?? '';
      row.push(escapeCSV(code));
    }
    if (positions.some((p) => p.section)) {
      row.push(escapeCSV(pos.section ?? ''));
    }
    lines.push(row.join(sep));
  }

  return lines.join('\r\n');
}

/** Generate and download a CSV export. */
export function exportToCSV(
  positions: ExchangePosition[],
  template: CountryTemplate,
  filename: string,
  options?: { includePrices?: boolean; separator?: ',' | ';' | '\t' },
): ExportResult {
  const csv = generateCSV(positions, template, options);
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' }); // BOM for Excel
  return {
    blob,
    filename: filename.endsWith('.csv') ? filename : `${filename}.csv`,
    positionCount: positions.filter((p) => !p.isSection).length,
    totalValue: positions.reduce((sum, p) => sum + (p.isSection ? 0 : p.total), 0),
  };
}

/** Trigger file download in the browser. */
export function downloadBlob(blob: Blob, filename: string): void {
  triggerDownload(blob, filename);
}
