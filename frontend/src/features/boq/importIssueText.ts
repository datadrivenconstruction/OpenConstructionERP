// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Wording for one warning or error line of the spreadsheet import preview.
 *
 * The server words its warnings in English. The one a user meets on every
 * national bill, a total, tax or recap line left out of the positions, comes
 * with a machine code and the row's own label, so it is worded here in the
 * reader's language instead; any other issue keeps the server's message.
 */

/** Minimal shape of the i18next `t` used here (repo convention). */
type Translate = (key: string, opts?: Record<string, unknown>) => string;

export interface ImportIssue {
  row?: number;
  /** Warnings carry `message`; parse errors from the importer carry `error`. */
  message?: string;
  error?: string;
  code?: string;
  label?: string;
}

export function importIssueText(issue: ImportIssue, t: Translate): string {
  const prefix =
    issue.row != null ? `${t('import.error_row', { defaultValue: 'Row {{row}}', row: issue.row })}: ` : '';
  const body =
    issue.code === 'summary_row_skipped' && issue.label
      ? t('boq.import_preview.summary_row_skipped', {
          defaultValue: '{{label}}: a total, tax or recap line, not imported as a position',
          label: issue.label,
        })
      : (issue.message ?? issue.error ?? '');
  return prefix + body;
}
