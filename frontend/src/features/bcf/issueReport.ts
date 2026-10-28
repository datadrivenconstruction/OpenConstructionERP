// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Printable HTML builder for a BCF issue / coordination report.
 *
 * Mirrors bim/printReport.ts: a pure (no-DOM) function that returns a clean
 * standalone document so the browser print dialog renders the issue register
 * without the app chrome - useful for a coordination-meeting hand-out or a
 * client-facing snapshot of the open issues. Escaping is delegated to the one
 * audited escaper in printReport.ts.
 */

import { escapeHtml } from '@/features/bim/printReport';

import type { IssueStats } from './issueStats';

/** One issue row as it appears in the report table (already localised /
 *  name-resolved by the caller). */
export interface IssueReportRow {
  index: number | null;
  title: string;
  status: string;
  priority: string;
  assignee: string;
  due: string | null;
  comments: number;
  description: string | null;
}

/** Localised labels; every field falls back to an English default. */
export interface IssueReportLabels {
  summary?: string;
  total?: string;
  open?: string;
  closed?: string;
  overdue?: string;
  unassigned?: string;
  issues?: string;
  colNum?: string;
  colTitle?: string;
  colStatus?: string;
  colPriority?: string;
  colAssignee?: string;
  colDue?: string;
  colComments?: string;
  none?: string;
}

export interface IssueReportParams {
  title: string;
  scopeLabel: string;
  generatedOn: string;
  stats: IssueStats;
  rows: IssueReportRow[];
  labels?: IssueReportLabels;
}

function summaryTable(stats: IssueStats, l: IssueReportLabels): string {
  const cell = (label: string, value: number, emphasise = false): string =>
    `<tr><td>${escapeHtml(label)}</td><td class="num${emphasise && value > 0 ? ' warn' : ''}">${value}</td></tr>`;
  return `
    <h2>${escapeHtml(l.summary ?? 'Summary')}</h2>
    <table class="summary">
      <tbody>
        ${cell(l.total ?? 'Total issues', stats.total)}
        ${cell(l.open ?? 'Open', stats.open)}
        ${cell(l.closed ?? 'Closed', stats.closed)}
        ${cell(l.overdue ?? 'Overdue', stats.overdue, true)}
        ${cell(l.unassigned ?? 'Unassigned (open)', stats.unassignedOpen, true)}
      </tbody>
    </table>`;
}

function issuesTable(rows: IssueReportRow[], l: IssueReportLabels): string {
  const head =
    `<tr>` +
    `<th class="num">${escapeHtml(l.colNum ?? '#')}</th>` +
    `<th>${escapeHtml(l.colTitle ?? 'Issue')}</th>` +
    `<th>${escapeHtml(l.colStatus ?? 'Status')}</th>` +
    `<th>${escapeHtml(l.colPriority ?? 'Priority')}</th>` +
    `<th>${escapeHtml(l.colAssignee ?? 'Assignee')}</th>` +
    `<th>${escapeHtml(l.colDue ?? 'Due')}</th>` +
    `<th class="num">${escapeHtml(l.colComments ?? 'Comments')}</th>` +
    `</tr>`;
  const dash = l.none ?? '-';
  const body = rows
    .map((r) => {
      const desc = r.description?.trim()
        ? `<div class="desc">${escapeHtml(r.description.trim())}</div>`
        : '';
      return (
        `<tr>` +
        `<td class="num">${r.index ?? ''}</td>` +
        `<td><div class="title">${escapeHtml(r.title)}</div>${desc}</td>` +
        `<td>${escapeHtml(r.status)}</td>` +
        `<td>${escapeHtml(r.priority || dash)}</td>` +
        `<td>${escapeHtml(r.assignee || dash)}</td>` +
        `<td>${escapeHtml(r.due || dash)}</td>` +
        `<td class="num">${r.comments}</td>` +
        `</tr>`
      );
    })
    .join('');
  return `
    <h2>${escapeHtml(l.issues ?? 'Issues')}</h2>
    <table>
      <thead>${head}</thead>
      <tbody>${body}</tbody>
    </table>`;
}

export function buildIssueReportHtml(params: IssueReportParams): string {
  const l = params.labels ?? {};
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
  th, td { border: 1px solid #ddd; padding: 5px 8px; text-align: left; vertical-align: top; }
  th { background: #f3f4f6; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  td.warn { color: #b91c1c; font-weight: 700; }
  table.summary { width: 280px; }
  .title { font-weight: 600; }
  .desc { color: #555; font-size: 11px; margin-top: 2px; white-space: pre-wrap; }
  .brand { margin-top: 28px; color: #9ca3af; font-size: 10px; }
  @media print { body { margin: 12mm; } }
</style>
</head>
<body>
  <h1>${escapeHtml(params.title)}</h1>
  <p class="meta">${escapeHtml(params.scopeLabel)} &middot; ${escapeHtml(params.generatedOn)}</p>
  ${summaryTable(params.stats, l)}
  ${issuesTable(params.rows, l)}
  <p class="brand">OpenConstructionERP</p>
</body>
</html>`;
}
