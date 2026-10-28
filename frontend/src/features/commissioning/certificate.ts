// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Commissioning certificate builder.
 *
 * Produces a printable handover document (and a spreadsheet export) for a
 * single building system: system details, readiness verdict, every
 * prefunctional / functional check with its result and note, and the issue
 * log. Fully client side, no extra dependency. The print document is written
 * into a fresh window that the opener drives to print, so no inline script
 * runs inside it (keeps it clear of any content-security policy on scripts).
 */

import {
  fetchChecklists,
  fetchItems,
  fetchIssues,
  fetchReadiness,
  type CxSystem,
  type CxChecklist,
  type CxChecklistItem,
  type CxIssue,
  type ReadinessSummary,
  type ItemStatus,
} from './api';
import { getIntlLocale } from '@/shared/lib/formatters';

/**
 * Minimal translate signature. The page passes a wrapper around react-i18next
 * `t` so we never have to reason about the full `TFunction` overloads here.
 */
export type Tr = (key: string, defaultValue: string, vars?: Record<string, unknown>) => string;

export interface CertMaps {
  /** system_type -> English fallback label (i18n keys still take priority). */
  typeLabels: Record<string, string>;
  /** status -> English fallback label. */
  statusLabels: Record<string, string>;
}

export interface CertChecklist {
  checklist: CxChecklist;
  items: CxChecklistItem[];
}

export interface CertificateData {
  system: CxSystem;
  /** Freshly fetched readiness, falling back to the embedded summary. */
  readiness: ReadinessSummary | null;
  checklists: CertChecklist[];
  issues: CxIssue[];
  projectName: string;
  generatedAt: Date;
}

/* ── Data gathering ────────────────────────────────────────────────────── */

/**
 * Pull every piece the certificate needs. Checklist items are loaded lazily
 * per checklist in the page, so we fetch them here on demand rather than
 * relying on cached queries.
 */
export async function gatherCertificateData(
  system: CxSystem,
  projectName: string,
): Promise<CertificateData> {
  const [checklists, issues, readiness] = await Promise.all([
    fetchChecklists(system.id),
    fetchIssues(system.id),
    fetchReadiness(system.id).catch(() => system.readiness),
  ]);

  const withItems = await Promise.all(
    checklists.map(async (c) => ({ checklist: c, items: await fetchItems(c.id) })),
  );

  return {
    system,
    readiness: readiness ?? system.readiness,
    checklists: withItems,
    issues,
    projectName,
    generatedAt: new Date(),
  };
}

/* ── Small formatting helpers ──────────────────────────────────────────── */

function escapeHtml(value: string | null | undefined): string {
  if (value == null) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function csvCell(value: string | number | null | undefined): string {
  const text = value == null ? '' : String(value);
  return `"${text.replace(/"/g, '""')}"`;
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString(getIntlLocale());
}

function itemStatusLabel(status: ItemStatus, tr: Tr): string {
  switch (status) {
    case 'pass':
      return tr('commissioning.result_pass', 'Pass');
    case 'fail':
      return tr('commissioning.result_fail', 'Fail');
    case 'na':
      return tr('commissioning.result_na', 'N/A');
    default:
      return tr('commissioning.item_pending', 'Pending');
  }
}

const STATUS_HEX: Record<ItemStatus, string> = {
  pass: '#16a34a',
  fail: '#dc2626',
  na: '#6b7280',
  pending: '#d97706',
};

const SEVERITY_HEX: Record<string, string> = {
  low: '#6b7280',
  medium: '#2563eb',
  high: '#d97706',
  critical: '#dc2626',
};

const LEVEL_HEX: Record<string, string> = {
  green: '#16a34a',
  amber: '#d97706',
  red: '#dc2626',
};

function typeLabel(system: CxSystem, tr: Tr, maps: CertMaps): string {
  const key = String(system.system_type);
  return tr(`commissioning.type_${key}`, maps.typeLabels[key] ?? key);
}

function statusLabel(system: CxSystem, tr: Tr, maps: CertMaps): string {
  return tr(`commissioning.status_${system.status}`, maps.statusLabels[system.status] ?? system.status);
}

/* ── Print (HTML) certificate ──────────────────────────────────────────── */

export function buildCertificateHtml(data: CertificateData, tr: Tr, maps: CertMaps): string {
  const { system, readiness, checklists, issues, projectName, generatedAt } = data;

  const title = tr('commissioning.cert_title', 'Commissioning Certificate');
  const dash = '-';

  const kvRow = (label: string, value: string): string =>
    `<tr><th>${escapeHtml(label)}</th><td>${value ? escapeHtml(value) : `<span class="muted">${dash}</span>`}</td></tr>`;

  const detailRows = [
    kvRow(tr('commissioning.cert_project', 'Project'), projectName),
    kvRow(tr('commissioning.field_name', 'System name'), system.name),
    kvRow(tr('commissioning.field_type', 'System type'), typeLabel(system, tr, maps)),
    kvRow(tr('commissioning.field_tag', 'Tag'), system.tag ?? ''),
    kvRow(tr('commissioning.field_location', 'Location'), system.location ?? ''),
    kvRow(tr('commissioning.cert_status', 'Status'), statusLabel(system, tr, maps)),
    system.description
      ? kvRow(tr('commissioning.cert_description', 'Description'), system.description)
      : '',
  ].join('');

  // Verdict block: a commissioned stamp, or the readiness scorecard.
  let verdictHtml: string;
  if (system.status === 'commissioned') {
    const on = fmtDate(system.commissioned_at);
    const by = system.commissioned_by ?? '';
    verdictHtml = `
      <div class="stamp">
        <div class="stamp-word">${escapeHtml(tr('commissioning.cert_stamp', 'COMMISSIONED'))}</div>
        <div class="stamp-meta">
          ${on ? escapeHtml(tr('commissioning.cert_commissioned_on', 'Commissioned on {{date}}', { date: on })) : ''}
          ${by ? ` ${dash} ${escapeHtml(tr('commissioning.cert_commissioned_by', 'by {{name}}', { name: by }))}` : ''}
        </div>
      </div>`;
  } else if (readiness && readiness.defined) {
    const level = readiness.readiness_level ?? 'red';
    const hex = LEVEL_HEX[level] ?? LEVEL_HEX.red;
    const pct = Math.round(readiness.readiness_pct);
    const verdict = readiness.can_commission
      ? tr('commissioning.cert_ready', 'Ready to commission')
      : tr('commissioning.cert_not_ready', 'Not ready to commission');
    const blockers =
      readiness.blocking_reasons.length > 0
        ? `<div class="blockers">
             <div class="blockers-h">${escapeHtml(tr('commissioning.blockers', 'Before commissioning'))}</div>
             <ul>${readiness.blocking_reasons.map((r) => `<li>${escapeHtml(r)}</li>`).join('')}</ul>
           </div>`
        : '';
    verdictHtml = `
      <div class="readiness">
        <div class="readiness-top">
          <span class="pill" style="background:${hex}">${pct}%</span>
          <span class="verdict" style="color:${hex}">${escapeHtml(verdict)}</span>
        </div>
        <div class="bar"><div class="bar-fill" style="width:${pct}%;background:${hex}"></div></div>
        <table class="counts">
          <tr>
            <td><b>${readiness.functional_passed}</b><span>${escapeHtml(tr('commissioning.cert_passed', 'Passed'))}</span></td>
            <td><b>${readiness.functional_failed}</b><span>${escapeHtml(tr('commissioning.result_fail', 'Fail'))}</span></td>
            <td><b>${readiness.functional_pending}</b><span>${escapeHtml(tr('commissioning.item_pending', 'Pending'))}</span></td>
            <td><b>${readiness.functional_na}</b><span>${escapeHtml(tr('commissioning.result_na', 'N/A'))}</span></td>
            <td><b>${readiness.open_critical_issues}</b><span>${escapeHtml(tr('commissioning.cert_open_critical', 'Open critical'))}</span></td>
          </tr>
        </table>
        ${blockers}
        ${readiness.formula ? `<div class="formula">${escapeHtml(readiness.formula)}</div>` : ''}
      </div>`;
  } else {
    verdictHtml = `<div class="readiness"><span class="muted">${escapeHtml(
      tr('commissioning.cert_no_tests', 'No functional checks have been defined yet.'),
    )}</span></div>`;
  }

  // Checklist tables.
  const checklistHtml =
    checklists.length === 0
      ? `<p class="muted">${escapeHtml(tr('commissioning.cert_no_checklists', 'No checklists recorded.'))}</p>`
      : checklists
          .map(({ checklist, items }) => {
            const kindLabel = tr(
              `commissioning.kind_${checklist.kind}`,
              checklist.kind === 'functional' ? 'Functional' : 'Prefunctional',
            );
            const passed = items.filter((i) => i.status === 'pass').length;
            const rows =
              items.length === 0
                ? `<tr><td colspan="4" class="muted">${escapeHtml(
                    tr('commissioning.no_items', 'No checks yet.'),
                  )}</td></tr>`
                : items
                    .map((item) => {
                      const hex = STATUS_HEX[item.status] ?? '#6b7280';
                      return `<tr>
                        <td class="seq">${item.sequence}</td>
                        <td>${escapeHtml(item.description)}</td>
                        <td><span class="tag" style="color:${hex};border-color:${hex}">${escapeHtml(
                          itemStatusLabel(item.status, tr),
                        )}</span></td>
                        <td>${item.result_note ? escapeHtml(item.result_note) : `<span class="muted">${dash}</span>`}</td>
                      </tr>`;
                    })
                    .join('');
            return `
              <div class="checklist">
                <div class="checklist-h">
                  <span class="kind">${escapeHtml(kindLabel)}</span>
                  <span class="checklist-title">${escapeHtml(checklist.title)}</span>
                  <span class="checklist-count">${passed}/${items.length} ${escapeHtml(
                    tr('commissioning.passed', 'passed'),
                  )}</span>
                </div>
                <table class="grid">
                  <thead>
                    <tr>
                      <th class="seq">#</th>
                      <th>${escapeHtml(tr('commissioning.cert_check', 'Check'))}</th>
                      <th>${escapeHtml(tr('commissioning.cert_result', 'Result'))}</th>
                      <th>${escapeHtml(tr('commissioning.cert_note', 'Note'))}</th>
                    </tr>
                  </thead>
                  <tbody>${rows}</tbody>
                </table>
              </div>`;
          })
          .join('');

  // Issue log.
  const issuesHtml =
    issues.length === 0
      ? `<p class="muted">${escapeHtml(tr('commissioning.no_issues', 'No issues logged.'))}</p>`
      : `<table class="grid">
          <thead>
            <tr>
              <th>${escapeHtml(tr('commissioning.severity', 'Severity'))}</th>
              <th>${escapeHtml(tr('commissioning.cert_state', 'State'))}</th>
              <th>${escapeHtml(tr('commissioning.cert_description', 'Description'))}</th>
              <th>${escapeHtml(tr('commissioning.cert_resolution', 'Resolution'))}</th>
            </tr>
          </thead>
          <tbody>
            ${issues
              .map((issue) => {
                const hex = SEVERITY_HEX[issue.severity] ?? '#6b7280';
                const stateLabel =
                  issue.status === 'closed'
                    ? tr('commissioning.closed', 'Closed')
                    : tr('commissioning.issue_open', 'Open');
                return `<tr>
                  <td><span class="tag" style="color:${hex};border-color:${hex}">${escapeHtml(
                    tr(`commissioning.severity_${issue.severity}`, issue.severity),
                  )}</span></td>
                  <td>${escapeHtml(stateLabel)}</td>
                  <td>${escapeHtml(issue.description)}</td>
                  <td>${issue.resolution ? escapeHtml(issue.resolution) : `<span class="muted">${dash}</span>`}</td>
                </tr>`;
              })
              .join('')}
          </tbody>
        </table>`;

  const sectionTitle = (label: string): string =>
    `<h2 class="section">${escapeHtml(label)}</h2>`;

  const generatedLine = tr('commissioning.cert_generated', 'Generated {{date}}', {
    date: generatedAt.toLocaleString(getIntlLocale()),
  });
  const refLine = tr('commissioning.cert_reference', 'Reference {{id}}', { id: system.id });
  const signAuthority = tr('commissioning.cert_sign_authority', 'Commissioning authority');
  const signClient = tr('commissioning.cert_sign_client', 'Client representative');
  const signName = tr('commissioning.cert_sign_name', 'Name and signature');
  const signDate = tr('commissioning.cert_sign_date', 'Date');
  const hint = tr('commissioning.cert_print_hint', 'Use your browser print dialog to save this as PDF.');

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>${escapeHtml(title)} ${dash} ${escapeHtml(system.name)}</title>
<style>
  * { box-sizing: border-box; }
  html, body {
    margin: 0;
    padding: 0;
    background: #f3f4f6;
    color: #111827;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  .doc {
    max-width: 820px;
    margin: 24px auto;
    background: #fff;
    padding: 40px 44px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
  }
  header.doc-head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    border-bottom: 2px solid #111827;
    padding-bottom: 14px;
    margin-bottom: 20px;
  }
  .doc-head h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: 0.02em; }
  .doc-head .sub { font-size: 12px; color: #6b7280; }
  .doc-head .right { text-align: right; font-size: 11px; color: #6b7280; line-height: 1.5; }
  h2.section {
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #374151;
    margin: 24px 0 8px;
    border-bottom: 1px solid #e5e7eb;
    padding-bottom: 4px;
  }
  table { width: 100%; border-collapse: collapse; }
  table.kv th {
    text-align: left;
    width: 170px;
    font-weight: 600;
    color: #6b7280;
    font-size: 12px;
    padding: 5px 8px 5px 0;
    vertical-align: top;
  }
  table.kv td { font-size: 12px; padding: 5px 0; }
  table.grid th, table.grid td {
    border: 1px solid #e5e7eb;
    padding: 6px 8px;
    font-size: 11px;
    text-align: left;
    vertical-align: top;
  }
  table.grid th { background: #f9fafb; font-weight: 600; color: #374151; }
  td.seq, th.seq { width: 34px; text-align: center; color: #6b7280; }
  .muted { color: #9ca3af; }
  .tag {
    display: inline-block;
    border: 1px solid;
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 10px;
    font-weight: 600;
  }
  .readiness { border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px 16px; }
  .readiness-top { display: flex; align-items: center; gap: 10px; }
  .pill { color: #fff; font-weight: 700; font-size: 13px; border-radius: 999px; padding: 2px 10px; }
  .verdict { font-weight: 600; font-size: 14px; }
  .bar { height: 6px; border-radius: 999px; background: #f3f4f6; overflow: hidden; margin: 10px 0 12px; }
  .bar-fill { height: 100%; border-radius: 999px; }
  table.counts td {
    text-align: center;
    border: 1px solid #e5e7eb;
    padding: 6px 4px;
    width: 20%;
  }
  table.counts b { display: block; font-size: 16px; }
  table.counts span { font-size: 10px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.03em; }
  .blockers { margin-top: 12px; border: 1px solid #fcd34d; background: #fffbeb; border-radius: 6px; padding: 8px 12px; }
  .blockers-h { font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; color: #b45309; font-weight: 700; margin-bottom: 4px; }
  .blockers ul { margin: 0; padding-left: 18px; }
  .blockers li { font-size: 11px; color: #374151; }
  .formula { margin-top: 10px; font-size: 10px; color: #9ca3af; }
  .stamp { border: 3px solid #16a34a; border-radius: 10px; padding: 14px 18px; text-align: center; }
  .stamp-word { color: #16a34a; font-size: 26px; font-weight: 800; letter-spacing: 0.08em; }
  .stamp-meta { font-size: 11px; color: #4b5563; margin-top: 4px; }
  .checklist { margin-bottom: 16px; }
  .checklist-h { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
  .kind { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: #2563eb; border: 1px solid #bfdbfe; border-radius: 4px; padding: 1px 6px; }
  .checklist-title { font-weight: 600; font-size: 13px; }
  .checklist-count { margin-left: auto; font-size: 11px; color: #6b7280; }
  .sign { display: flex; gap: 40px; margin-top: 40px; }
  .sign-col { flex: 1; }
  .sign-line { border-top: 1px solid #9ca3af; margin-top: 34px; padding-top: 4px; font-size: 11px; color: #6b7280; }
  .sign-role { font-size: 12px; font-weight: 600; color: #374151; }
  footer.doc-foot { margin-top: 28px; border-top: 1px solid #e5e7eb; padding-top: 10px; font-size: 10px; color: #9ca3af; display: flex; justify-content: space-between; }
  @media print {
    html, body { background: #fff; }
    .doc { margin: 0; box-shadow: none; padding: 0; max-width: none; }
    .no-print { display: none !important; }
    h2.section, .checklist { page-break-inside: avoid; }
  }
</style>
</head>
<body>
  <div class="doc">
    <header class="doc-head">
      <div>
        <h1>${escapeHtml(title)}</h1>
        <div class="sub">${escapeHtml(system.name)}${system.tag ? ` ${dash} ${escapeHtml(system.tag)}` : ''}</div>
      </div>
      <div class="right">
        <div>${escapeHtml(generatedLine)}</div>
        <div>${escapeHtml(refLine)}</div>
      </div>
    </header>

    ${sectionTitle(tr('commissioning.cert_system_details', 'System details'))}
    <table class="kv"><tbody>${detailRows}</tbody></table>

    ${sectionTitle(tr('commissioning.cert_readiness', 'Readiness'))}
    ${verdictHtml}

    ${sectionTitle(tr('commissioning.checklists', 'Checklists'))}
    ${checklistHtml}

    ${sectionTitle(tr('commissioning.issues', 'Issues'))}
    ${issuesHtml}

    <div class="sign">
      <div class="sign-col">
        <div class="sign-role">${escapeHtml(signAuthority)}</div>
        <div class="sign-line">${escapeHtml(signName)}</div>
        <div class="sign-line">${escapeHtml(signDate)}</div>
      </div>
      <div class="sign-col">
        <div class="sign-role">${escapeHtml(signClient)}</div>
        <div class="sign-line">${escapeHtml(signName)}</div>
        <div class="sign-line">${escapeHtml(signDate)}</div>
      </div>
    </div>

    <footer class="doc-foot">
      <span>${escapeHtml(title)}</span>
      <span class="no-print">${escapeHtml(hint)}</span>
    </footer>
  </div>
</body>
</html>`;
}

/**
 * Open the certificate in a new window and ask the browser to print it. The
 * window keeps its content if printing is dismissed, so the user can still
 * read it or print manually. Returns false when the pop-up was blocked.
 */
export function openCertificatePrint(html: string): boolean {
  const win = window.open('', '_blank', 'width=920,height=1000');
  if (!win) return false;
  win.document.open();
  win.document.write(html);
  win.document.close();
  win.focus();
  // Let the new document lay out before invoking print.
  window.setTimeout(() => {
    try {
      win.print();
    } catch {
      /* user can still print from the browser menu */
    }
  }, 300);
  return true;
}

/* ── CSV export ────────────────────────────────────────────────────────── */

export function buildCertificateCsv(data: CertificateData, tr: Tr, maps: CertMaps): string {
  const { system, readiness, checklists, issues, projectName, generatedAt } = data;
  const yes = tr('common.yes', 'Yes');
  const no = tr('common.no', 'No');
  const lines: string[] = [];

  lines.push([csvCell(tr('commissioning.cert_title', 'Commissioning Certificate'))].join(','));
  lines.push([csvCell(tr('commissioning.cert_generated_label', 'Generated')), csvCell(generatedAt.toLocaleString(getIntlLocale()))].join(','));
  lines.push([csvCell(tr('commissioning.cert_project', 'Project')), csvCell(projectName)].join(','));
  lines.push([csvCell(tr('commissioning.field_name', 'System name')), csvCell(system.name)].join(','));
  lines.push([csvCell(tr('commissioning.field_type', 'System type')), csvCell(typeLabel(system, tr, maps))].join(','));
  lines.push([csvCell(tr('commissioning.field_tag', 'Tag')), csvCell(system.tag ?? '')].join(','));
  lines.push([csvCell(tr('commissioning.field_location', 'Location')), csvCell(system.location ?? '')].join(','));
  lines.push([csvCell(tr('commissioning.cert_status', 'Status')), csvCell(statusLabel(system, tr, maps))].join(','));
  if (readiness && readiness.defined) {
    lines.push(
      [
        csvCell(tr('commissioning.cert_readiness', 'Readiness')),
        csvCell(`${Math.round(readiness.readiness_pct)}%`),
      ].join(','),
    );
    lines.push(
      [
        csvCell(tr('commissioning.cert_can_commission', 'Can commission')),
        csvCell(readiness.can_commission ? yes : no),
      ].join(','),
    );
  }

  lines.push('');
  lines.push(
    [
      csvCell(tr('commissioning.cert_checklist', 'Checklist')),
      csvCell(tr('commissioning.checklist_kind', 'Checklist kind')),
      csvCell('#'),
      csvCell(tr('commissioning.cert_check', 'Check')),
      csvCell(tr('commissioning.cert_result', 'Result')),
      csvCell(tr('commissioning.cert_note', 'Note')),
      csvCell(tr('commissioning.cert_verified_at', 'Verified at')),
    ].join(','),
  );
  for (const { checklist, items } of checklists) {
    const kindLabel = tr(
      `commissioning.kind_${checklist.kind}`,
      checklist.kind === 'functional' ? 'Functional' : 'Prefunctional',
    );
    for (const item of items) {
      lines.push(
        [
          csvCell(checklist.title),
          csvCell(kindLabel),
          csvCell(item.sequence),
          csvCell(item.description),
          csvCell(itemStatusLabel(item.status, tr)),
          csvCell(item.result_note ?? ''),
          csvCell(fmtDate(item.verified_at)),
        ].join(','),
      );
    }
  }

  lines.push('');
  lines.push(
    [
      csvCell(tr('commissioning.issues', 'Issues')),
      csvCell(tr('commissioning.severity', 'Severity')),
      csvCell(tr('commissioning.cert_state', 'State')),
      csvCell(tr('commissioning.cert_resolution', 'Resolution')),
      csvCell(tr('commissioning.cert_raised_at', 'Raised at')),
    ].join(','),
  );
  for (const issue of issues) {
    lines.push(
      [
        csvCell(issue.description),
        csvCell(tr(`commissioning.severity_${issue.severity}`, issue.severity)),
        csvCell(
          issue.status === 'closed'
            ? tr('commissioning.closed', 'Closed')
            : tr('commissioning.issue_open', 'Open'),
        ),
        csvCell(issue.resolution ?? ''),
        csvCell(fmtDate(issue.created_at)),
      ].join(','),
    );
  }

  return lines.join('\n');
}

/** Trigger a client-side CSV download (UTF-8 with BOM for spreadsheet apps). */
export function downloadCsv(filename: string, csv: string): void {
  // Prepend a UTF-8 BOM (built from its code point, not a literal invisible
  // character) so spreadsheet apps read non-ASCII names in the right encoding.
  const bom = String.fromCharCode(0xfeff);
  const blob = new Blob([bom, csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** File-safe slug from an arbitrary system name. */
export function certFileSlug(name: string): string {
  const slug = name
    .trim()
    .replace(/[^a-z0-9]+/gi, '_')
    .replace(/^_+|_+$/g, '')
    .toLowerCase();
  return slug || 'system';
}
