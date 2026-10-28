// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Printable HTML builder for the BIM filter report (B5).
 *
 * The on-screen report lives in a React modal, but "Print / Save as PDF"
 * opens a clean standalone document so the browser print dialog renders the
 * tables without the app chrome. Keeping the HTML builder pure (no DOM) makes
 * it unit-testable and keeps the escaping in one audited place.
 */
import { QUANTITY_FIELDS, type QuantitySummary } from './boqSummary';
import { toDisplayQuantity, displayUnitFor } from '@/shared/lib/unitConversion';
import { getIntlLocale } from '@/shared/lib/formatters';

export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function fmt(n: number): string {
  // Group thousands, keep up to 3 decimals, drop trailing zeros.
  return n.toLocaleString(getIntlLocale(), { maximumFractionDigits: 3 });
}

export interface ReportSection {
  heading: string;
  groupLabel: string;
  summary: QuantitySummary;
}

export interface BuildReportHtmlParams {
  title: string;
  scopeLabel: string;
  generatedOn: string;
  sections: ReportSection[];
  /** The user's measurement system. The summaries are metric-canonical; when
   *  `imperial` the quantity values + their fallback header units are restated
   *  for display (totals/money are unaffected - these are quantity columns).
   *  Defaults to `metric` so existing callers stay byte-identical. */
  system?: 'metric' | 'imperial';
  /** Localised column labels in QUANTITY_FIELDS order, plus the leading
   *  group + count headers. Falls back to the English defaults. */
  labels?: {
    group?: string;
    count?: string;
    total?: string;
    quantities?: string[];
  };
}

function sectionTable(
  section: ReportSection,
  labels: Required<BuildReportHtmlParams>['labels'],
  system: 'metric' | 'imperial',
): string {
  // Restate each metric-canonical quantity column into the display system.
  // `conv(value, i)` converts by the column's metric unit; the fallback
  // header unit is relabelled the same way. Unmapped units pass through.
  const conv = (value: number, i: number) =>
    toDisplayQuantity(value, QUANTITY_FIELDS[i]?.unit ?? '', system).value;
  const qtyHeaders = QUANTITY_FIELDS.map(
    (f, i) =>
      `<th class="num">${escapeHtml(
        labels.quantities?.[i] ?? `${f.label} (${displayUnitFor(f.unit, system)})`,
      )}</th>`,
  ).join('');
  const rows = section.summary.rows
    .map((r) => {
      const qcells = r.quantities.map((q, i) => `<td class="num">${fmt(conv(q, i))}</td>`).join('');
      return `<tr><td>${escapeHtml(r.key)}</td><td class="num">${fmt(r.count)}</td>${qcells}</tr>`;
    })
    .join('');
  const totalQ = section.summary.totals.quantities
    .map((q, i) => `<td class="num">${fmt(conv(q, i))}</td>`)
    .join('');
  return `
    <h2>${escapeHtml(section.heading)}</h2>
    <table>
      <thead>
        <tr><th>${escapeHtml(section.groupLabel)}</th><th class="num">${escapeHtml(labels.count ?? 'Count')}</th>${qtyHeaders}</tr>
      </thead>
      <tbody>${rows}</tbody>
      <tfoot>
        <tr><td>${escapeHtml(labels.total ?? 'TOTAL')}</td><td class="num">${fmt(section.summary.totals.count)}</td>${totalQ}</tr>
      </tfoot>
    </table>`;
}

export function buildReportHtml(params: BuildReportHtmlParams): string {
  const labels = params.labels ?? {};
  const system = params.system ?? 'metric';
  const body = params.sections.map((s) => sectionTable(s, labels, system)).join('\n');
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>${escapeHtml(params.title)}</title>
<style>
  body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; color: #111; margin: 32px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .meta { color: #666; font-size: 12px; margin: 0 0 20px; }
  h2 { font-size: 14px; margin: 24px 0 6px; }
  table { border-collapse: collapse; width: 100%; font-size: 12px; margin-bottom: 8px; }
  th, td { border: 1px solid #ddd; padding: 5px 8px; text-align: left; }
  th { background: #f3f4f6; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  tfoot td { font-weight: 700; background: #f9fafb; }
  .brand { margin-top: 28px; color: #9ca3af; font-size: 10px; }
  @media print { body { margin: 12mm; } }
</style>
</head>
<body>
  <h1>${escapeHtml(params.title)}</h1>
  <p class="meta">${escapeHtml(params.scopeLabel)} &middot; ${escapeHtml(params.generatedOn)}</p>
  ${body}
  <p class="brand">OpenConstructionERP</p>
</body>
</html>`;
}
