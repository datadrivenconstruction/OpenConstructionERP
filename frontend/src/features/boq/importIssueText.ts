// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Wording for one warning or error line of a spreadsheet import report.
 *
 * The server words its issues in English. The ones a user meets on a national
 * bill come with a machine code and the values that matter, so they are worded
 * here in the reader's language instead:
 *
 * - `summary_row_skipped`: a total, tax or recap line left out of the positions;
 * - `sheet_not_read`: a worksheet the reader did not read, and why;
 * - `dot_read_as_thousands`: a typed number whose dots were read as thousands;
 * - `header_not_recognised`: a header row that names no description, or nothing
 *   to price by, with the headings that were not recognised.
 *
 * Any other issue keeps the server's message. A workbook is read across all its
 * item sheets, so a row number alone is ambiguous: an issue that names its
 * sheet is prefixed with it.
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
  sheet?: string;
  reason?: string;
  /** The sheet a skipped copy repeats. */
  of?: string;
  text?: string;
  value?: number;
  missing?: string[];
  unrecognised?: string[];
}

function prefixOf(issue: ImportIssue, t: Translate): string {
  if (issue.sheet && issue.row != null) {
    return `${t('boq.import_issue.sheet_row', {
      defaultValue: 'Sheet {{sheet}}, row {{row}}',
      sheet: issue.sheet,
      row: issue.row,
    })}: `;
  }
  if (issue.row != null) return `${t('import.error_row', { defaultValue: 'Row {{row}}', row: issue.row })}: `;
  return '';
}

function sheetNotRead(issue: ImportIssue, t: Translate): string {
  if (issue.reason === 'hidden') {
    return t('boq.import_issue.sheet_hidden', {
      defaultValue: 'Sheet {{sheet}} was not read: it is hidden',
      sheet: issue.sheet,
    });
  }
  if (issue.reason === 'duplicate') {
    return t('boq.import_issue.sheet_duplicate', {
      defaultValue: 'Sheet {{sheet}} was not read: it repeats the lines of sheet {{of}}',
      sheet: issue.sheet,
      of: issue.of ?? '',
    });
  }
  return t('boq.import_issue.sheet_no_items', {
    defaultValue: 'Sheet {{sheet}} was not read: it has no header naming a description with a quantity, unit or rate',
    sheet: issue.sheet,
  });
}

function headerNotRecognised(issue: ImportIssue, t: Translate): string {
  const missing = issue.missing ?? [];
  const needs = missing.includes('description')
    ? missing.includes('quantity_or_rate')
      ? t('boq.import_issue.header_needs_both', {
          defaultValue: 'The header row names no description column and no quantity, unit or rate column',
        })
      : t('boq.import_issue.header_needs_description', {
          defaultValue: 'The header row names no description column',
        })
    : t('boq.import_issue.header_needs_quantity', {
        defaultValue: 'The header row names no quantity, unit or rate column',
      });
  const unknown = issue.unrecognised ?? [];
  if (unknown.length === 0) return needs;
  return `${needs}. ${t('boq.import_issue.header_unrecognised', {
    defaultValue: 'Headings not recognised: {{headings}}',
    headings: unknown.slice(0, 12).join(', '),
  })}`;
}

export function importIssueText(
  issue: ImportIssue,
  t: Translate,
  formatNumber: (value: number) => string = String,
): string {
  let body: string;
  if (issue.code === 'summary_row_skipped' && issue.label) {
    body = t('boq.import_preview.summary_row_skipped', {
      defaultValue: '{{label}}: a total, tax or recap line, not imported as a position',
      label: issue.label,
    });
  } else if (issue.code === 'sheet_not_read' && issue.sheet) {
    // A note about a whole sheet: the sheet is the subject, not a prefix.
    return sheetNotRead(issue, t);
  } else if (issue.code === 'dot_read_as_thousands' && issue.text != null && issue.value != null) {
    body = t('boq.import_issue.dot_thousands', {
      defaultValue: '{{text}} was read as {{value}}: the dot separates thousands',
      text: issue.text,
      value: formatNumber(issue.value),
    });
  } else if (issue.code === 'header_not_recognised') {
    const where = issue.sheet
      ? `${t('boq.import_issue.sheet', { defaultValue: 'Sheet {{sheet}}', sheet: issue.sheet })}: `
      : '';
    return where + headerNotRecognised(issue, t);
  } else {
    body = issue.message ?? issue.error ?? '';
  }
  return prefixOf(issue, t) + body;
}
