// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Printable minutes of a model-review session - the record a coordinator
 * leaves the meeting with.
 *
 * The session itself is not a new kind of stored object: every decision it
 * records is already persisted as BCF (a status change on a topic, a comment
 * with its author and timestamp), and the hand-over file is the `.bcfzip` of
 * exactly the walked issues. What is missing without this module is the human
 * artefact - one page saying which model was reviewed, who chaired it, what was
 * agreed on each issue, and what is still open. That page is built here.
 *
 * Pure and DOM-free, mirroring bim/printReport.ts and bcf/issueReport.ts, so it
 * is unit-testable and the caller owns the print window. Escaping is delegated
 * to the one audited escaper in printReport.ts.
 */

import { escapeHtml } from './printReport';

/** One thing that was decided about one issue during the session. */
export interface ReviewDecision {
  /** BCF topic guid the decision belongs to. */
  guid: string;
  /** Issue title as it read during the session. */
  title: string;
  /** Status before the change, when the decision changed a status. */
  statusFrom?: string | null;
  /** Status after the change. */
  statusTo?: string | null;
  /** Note posted as a BCF comment during the session. */
  note?: string | null;
}

/** One issue that was on the agenda, with the state it ended the session in. */
export interface ReviewAgendaRow {
  index: number | null;
  title: string;
  status: string;
  priority: string;
  assignee: string;
  due: string | null;
}

/** Localised labels; every field falls back to an English default. */
export interface ReviewMinutesLabels {
  model?: string;
  chair?: string;
  held?: string;
  agendaSize?: string;
  decisionsTaken?: string;
  stillOpen?: string;
  decisions?: string;
  agenda?: string;
  colIssue?: string;
  colChange?: string;
  colNote?: string;
  colNum?: string;
  colStatus?: string;
  colPriority?: string;
  colAssignee?: string;
  colDue?: string;
  noDecisions?: string;
  none?: string;
}

export interface ReviewMinutesParams {
  /** Document heading, e.g. "Model review minutes". */
  title: string;
  /** Model that was on screen, or null when the review was register-only. */
  modelName: string | null;
  /** Who ran the session (already resolved to a human name). */
  chair: string;
  /** Localised date-time the session was held. */
  heldOn: string;
  /** Issues that were on the agenda, in the order they were walked. */
  agenda: ReviewAgendaRow[];
  /** Decisions taken, in the order they were taken. */
  decisions: ReviewDecision[];
  /** Agenda issues still not closed when the session ended. */
  stillOpen: number;
  labels?: ReviewMinutesLabels;
}

function metaTable(params: ReviewMinutesParams, l: ReviewMinutesLabels): string {
  const dash = l.none ?? '-';
  const row = (label: string, value: string): string =>
    `<tr><td>${escapeHtml(label)}</td><td>${escapeHtml(value)}</td></tr>`;
  return `
    <table class="summary">
      <tbody>
        ${row(l.model ?? 'Model', params.modelName || dash)}
        ${row(l.chair ?? 'Chaired by', params.chair || dash)}
        ${row(l.held ?? 'Held', params.heldOn)}
        ${row(l.agendaSize ?? 'Issues reviewed', String(params.agenda.length))}
        ${row(l.decisionsTaken ?? 'Decisions taken', String(params.decisions.length))}
        ${row(l.stillOpen ?? 'Still open', String(params.stillOpen))}
      </tbody>
    </table>`;
}

function decisionsTable(params: ReviewMinutesParams, l: ReviewMinutesLabels): string {
  const dash = l.none ?? '-';
  if (params.decisions.length === 0) {
    return `
    <h2>${escapeHtml(l.decisions ?? 'Decisions')}</h2>
    <p class="empty">${escapeHtml(l.noDecisions ?? 'No status changes or notes were recorded in this session.')}</p>`;
  }
  const head =
    `<tr>` +
    `<th>${escapeHtml(l.colIssue ?? 'Issue')}</th>` +
    `<th>${escapeHtml(l.colChange ?? 'Change')}</th>` +
    `<th>${escapeHtml(l.colNote ?? 'Note')}</th>` +
    `</tr>`;
  const body = params.decisions
    .map((d) => {
      const change =
        d.statusTo && d.statusTo !== d.statusFrom
          ? `${d.statusFrom || dash} → ${d.statusTo}`
          : dash;
      return (
        `<tr>` +
        `<td><div class="title">${escapeHtml(d.title)}</div></td>` +
        `<td>${escapeHtml(change)}</td>` +
        `<td>${escapeHtml(d.note || dash)}</td>` +
        `</tr>`
      );
    })
    .join('');
  return `
    <h2>${escapeHtml(l.decisions ?? 'Decisions')}</h2>
    <table>
      <thead>${head}</thead>
      <tbody>${body}</tbody>
    </table>`;
}

function agendaTable(params: ReviewMinutesParams, l: ReviewMinutesLabels): string {
  const dash = l.none ?? '-';
  const head =
    `<tr>` +
    `<th class="num">${escapeHtml(l.colNum ?? '#')}</th>` +
    `<th>${escapeHtml(l.colIssue ?? 'Issue')}</th>` +
    `<th>${escapeHtml(l.colStatus ?? 'Status')}</th>` +
    `<th>${escapeHtml(l.colPriority ?? 'Priority')}</th>` +
    `<th>${escapeHtml(l.colAssignee ?? 'Assigned to')}</th>` +
    `<th>${escapeHtml(l.colDue ?? 'Due date')}</th>` +
    `</tr>`;
  const body = params.agenda
    .map(
      (r) =>
        `<tr>` +
        `<td class="num">${r.index ?? ''}</td>` +
        `<td><div class="title">${escapeHtml(r.title)}</div></td>` +
        `<td>${escapeHtml(r.status)}</td>` +
        `<td>${escapeHtml(r.priority || dash)}</td>` +
        `<td>${escapeHtml(r.assignee || dash)}</td>` +
        `<td>${escapeHtml(r.due || dash)}</td>` +
        `</tr>`,
    )
    .join('');
  return `
    <h2>${escapeHtml(l.agenda ?? 'Issues reviewed')}</h2>
    <table>
      <thead>${head}</thead>
      <tbody>${body}</tbody>
    </table>`;
}

/** Build the standalone minutes document for a finished review session. */
export function buildReviewMinutesHtml(params: ReviewMinutesParams): string {
  const l = params.labels ?? {};
  const subtitle = [params.modelName, params.heldOn].filter(Boolean).join(' · ');
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
  table.summary { width: 340px; }
  .title { font-weight: 600; }
  .empty { color: #666; font-size: 12px; }
  .brand { margin-top: 28px; color: #9ca3af; font-size: 10px; }
  @media print { body { margin: 12mm; } }
</style>
</head>
<body>
  <h1>${escapeHtml(params.title)}</h1>
  <p class="meta">${escapeHtml(subtitle)}</p>
  ${metaTable(params, l)}
  ${decisionsTable(params, l)}
  ${agendaTable(params, l)}
  <p class="brand">OpenConstructionERP</p>
</body>
</html>`;
}
