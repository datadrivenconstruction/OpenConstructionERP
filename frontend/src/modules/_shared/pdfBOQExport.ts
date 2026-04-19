/**
 * Shared PDF BOQ export utility.
 *
 * Generates a simple PDF BOQ report using basic HTML-to-print approach.
 * No heavy PDF library needed — we open a print window.
 */

import type { ExchangePosition, CountryTemplate } from './templateTypes';

const htmlEscape = (value: string | number): string =>
  String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

/** Generate a printable HTML string for a BOQ report. */
export function generateBOQPrintHTML(
  positions: ExchangePosition[],
  template: CountryTemplate,
  options: {
    projectName?: string;
    boqName?: string;
    includePrices?: boolean;
    date?: string;
  } = {},
): string {
  const { projectName = 'Project', boqName = 'Bill of Quantities', includePrices = true, date = new Date().toLocaleDateString() } = options;

  const totalValue = positions.reduce((sum, p) => sum + (p.isSection ? 0 : p.total), 0);
  const posCount = positions.filter((p) => !p.isSection).length;

  const formatCurrency = (val: number) =>
    `${htmlEscape(template.currencySymbol)}${val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  const rows = positions
    .map((pos) => {
      if (pos.isSection) {
        return `<tr class="section"><td colspan="${includePrices ? 6 : 4}"><strong>${htmlEscape(pos.ordinal)} ${htmlEscape(pos.description)}</strong></td></tr>`;
      }
      return `<tr>
        <td>${htmlEscape(pos.ordinal)}</td>
        <td>${htmlEscape(pos.description)}</td>
        <td class="center">${htmlEscape(pos.unit)}</td>
        <td class="right">${pos.quantity.toFixed(3)}</td>
        ${includePrices ? `<td class="right">${formatCurrency(pos.unitRate)}</td><td class="right">${formatCurrency(pos.total)}</td>` : ''}
      </tr>`;
    })
    .join('\n');

  return `<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>${htmlEscape(boqName)}</title>
<style>
  body { font-family: Arial, sans-serif; font-size: 10pt; margin: 20mm; color: #222; }
  h1 { font-size: 16pt; margin-bottom: 4px; }
  h2 { font-size: 12pt; color: #555; margin-top: 0; }
  .meta { color: #777; font-size: 9pt; margin-bottom: 16px; }
  table { width: 100%; border-collapse: collapse; margin-top: 12px; }
  th { background: #f5f5f5; padding: 6px 8px; text-align: left; border-bottom: 2px solid #ddd; font-size: 9pt; }
  td { padding: 4px 8px; border-bottom: 1px solid #eee; }
  .right { text-align: right; }
  .center { text-align: center; }
  .section td { background: #f9f9f9; padding: 8px; }
  .total { font-weight: bold; border-top: 2px solid #333; font-size: 11pt; }
  @media print { body { margin: 10mm; } }
</style>
</head><body>
  <h1>${htmlEscape(projectName)}</h1>
  <h2>${htmlEscape(boqName)} — ${htmlEscape(template.name)} (${htmlEscape(template.country)})</h2>
  <div class="meta">${htmlEscape(date)} | ${posCount} positions | Standard: ${htmlEscape(template.classification)} | Currency: ${htmlEscape(template.currency)}</div>
  <table>
    <thead>
      <tr>
        <th style="width:8%">No.</th>
        <th>Description</th>
        <th style="width:6%" class="center">Unit</th>
        <th style="width:10%" class="right">Qty</th>
        ${includePrices ? `<th style="width:12%" class="right">Rate</th><th style="width:12%" class="right">Total</th>` : ''}
      </tr>
    </thead>
    <tbody>
      ${rows}
    </tbody>
    ${includePrices ? `<tfoot><tr class="total"><td colspan="5" class="right">Grand Total:</td><td class="right">${formatCurrency(totalValue)}</td></tr></tfoot>` : ''}
  </table>
</body></html>`;
}

/** Open a print dialog with the generated BOQ PDF. */
export function printBOQReport(
  positions: ExchangePosition[],
  template: CountryTemplate,
  options?: { projectName?: string; boqName?: string; includePrices?: boolean },
): void {
  const html = generateBOQPrintHTML(positions, template, options);
  const win = window.open('', '_blank');
  if (win) {
    win.document.write(html);
    win.document.close();
    win.focus();
    setTimeout(() => win.print(), 500);
  }
}
