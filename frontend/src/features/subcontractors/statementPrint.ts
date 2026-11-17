// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The print view of a pay application's progress statement.
 *
 * Built as a plain HTML document so it prints the same from any browser and
 * needs no PDF library: the person chooses "Save as PDF" in the print dialog.
 * Every label comes in through `labels`, so this file holds no words.
 */

import type { PayAppStatement } from './api';

export interface StatementLabels {
  title: string;
  application: string;
  period: string;
  status: string;
  scheduled_value: string;
  previous: string;
  this_period: string;
  total_completed: string;
  percent_complete: string;
  retention: string;
  balance_to_finish: string;
  original_contract_sum: string;
  change_orders: string;
  contract_sum_to_date: string;
  completed_to_date: string;
  retention_held: string;
  previous_certified: string;
  current_due: string;
  total: string;
}

export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Format a decimal string with the given locale; a value that is not a number is shown as it came. */
export function formatAmount(value: string | null | undefined, currency: string, locale?: string): string {
  if (value === null || value === undefined || value === '') return '';
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  try {
    return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(n);
  } catch {
    return new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
  }
}

export function formatPercent(value: string | null | undefined, locale?: string): string {
  if (value === null || value === undefined || value === '') return '';
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  return `${new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 2 }).format(n)} %`;
}

export function buildStatementHtml(
  statement: PayAppStatement,
  labels: StatementLabels,
  subject: string,
  locale?: string,
): string {
  const cur = statement.currency || 'USD';
  const money = (v: string | null | undefined) => escapeHtml(formatAmount(v, cur, locale));
  const e = escapeHtml;
  const rows = statement.lines
    .map(
      (l) => `<tr><td>${e(l.name)}</td><td class="n">${money(l.scheduled_value)}</td><td class="n">${money(l.previous)}</td>` +
        `<td class="n">${money(l.this_period)}</td><td class="n">${money(l.total_completed)}</td>` +
        `<td class="n">${e(formatPercent(l.percent_complete, locale))}</td><td class="n">${money(l.retention)}</td>` +
        `<td class="n">${money(l.balance_to_finish)}</td></tr>`,
    )
    .join('');
  const s = statement.summary;
  const summaryRows: [string, string][] = [
    [labels.original_contract_sum, s.original_contract_sum],
    [labels.change_orders, s.change_orders],
    [labels.contract_sum_to_date, s.contract_sum_to_date],
    [labels.completed_to_date, s.completed_to_date],
    [labels.retention_held, s.retention_held],
    [labels.previous_certified, s.previous_certified],
    [labels.current_due, s.current_due],
  ];
  const summary = summaryRows
    .map(([k, v]) => `<tr><th>${e(k)}</th><td class="n">${money(v)}</td></tr>`)
    .join('');
  const period = [statement.period_start, statement.period_end].filter(Boolean).join(' - ');
  return `<!doctype html><html><head><meta charset="utf-8"><title>${e(labels.title)} ${e(statement.application_number)}</title>
<style>
body{font-family:system-ui,Arial,sans-serif;font-size:12px;color:#111;margin:24px}
h1{font-size:18px;margin:0 0 4px}
p.meta{margin:0 0 12px;color:#444}
table{border-collapse:collapse;width:100%;margin-bottom:16px}
th,td{border:1px solid #999;padding:4px 6px;text-align:left}
td.n{text-align:right;font-variant-numeric:tabular-nums}
thead th{background:#eee}
table.sum{width:50%;margin-left:auto}
@media print{body{margin:0}}
</style></head><body>
<h1>${e(labels.title)}</h1>
<p class="meta">${e(subject)} &middot; ${e(labels.application)} ${e(statement.application_number)} &middot; ${e(labels.period)} ${e(period || '-')} &middot; ${e(labels.status)} ${e(statement.status)}</p>
<table><thead><tr><th></th><th>${e(labels.scheduled_value)}</th><th>${e(labels.previous)}</th><th>${e(labels.this_period)}</th>
<th>${e(labels.total_completed)}</th><th>${e(labels.percent_complete)}</th><th>${e(labels.retention)}</th><th>${e(labels.balance_to_finish)}</th></tr></thead>
<tbody>${rows}</tbody>
<tfoot><tr><th>${e(labels.total)}</th><td class="n">${money(s.scheduled_total)}</td><td class="n">${money(s.previous_completed)}</td>
<td class="n">${money(s.this_period)}</td><td class="n">${money(s.completed_to_date)}</td><td class="n">${e(formatPercent(s.percent_complete, locale))}</td>
<td class="n">${money(s.retention_held)}</td><td class="n">${money(s.balance_to_finish)}</td></tr></tfoot></table>
<table class="sum"><tbody>${summary}</tbody></table>
</body></html>`;
}

/** Open the statement in a new window and start the browser's print dialog. */
export function printStatement(html: string): boolean {
  const w = window.open('', '_blank', 'noopener=no,width=900,height=700');
  if (!w) return false;
  w.document.open();
  w.document.write(html);
  w.document.close();
  w.focus();
  w.print();
  return true;
}
