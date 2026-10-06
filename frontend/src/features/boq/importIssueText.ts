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
 * - `comma_read_as_thousands`: the same for commas, in a decimal-point market;
 * - `header_not_recognised`: a header row that names no description, or nothing
 *   to price by, with the headings that were not recognised;
 * - `column_mapping_not_applied`: a column mapping chosen in the preview that
 *   the import could not lay over the file, and why;
 * - `xpwe_*`: the notes of an XPWE (Italian estimating XML) import, which name
 *   the bill item they concern by its ordinal rather than a row number.
 *
 * Any other issue keeps the server's message. A workbook is read across all its
 * item sheets, so a row number alone is ambiguous: an issue that names its
 * sheet is prefixed with it.
 */

import { fmtList } from '@/shared/lib/formatters';

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
  /** The bill item an XPWE note concerns, by its ordinal in the imported bill. */
  ordinal?: string;
  ref?: string;
  computed?: number;
  declared?: number;
  encoding?: string;
  count?: number;
  /** The item that first used an ID another item repeats. */
  first?: string;
  /** The signed sum of the lines an XPWE import moved into the bill's deductions line. */
  amount?: number;
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
  // Only the XPWE notes are worded without their item; other importers'
  // messages that carry an ordinal already name it.
  if (issue.ordinal && issue.code?.startsWith('xpwe_')) {
    return `${t('boq.import_issue.item', { defaultValue: 'Item {{ordinal}}', ordinal: issue.ordinal })}: `;
  }
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
    headings: fmtList(unknown.slice(0, 12)),
  })}`;
}

function mappingNotApplied(issue: ImportIssue, t: Translate): string {
  if (issue.reason === 'profile') {
    return t('boq.import_issue.mapping_profile', {
      defaultValue: 'The column mapping was not used: this workbook was read through its national profile',
    });
  }
  if (issue.reason === 'different_header') {
    return t('boq.import_issue.mapping_different_header', {
      defaultValue: 'The column mapping was not used on this sheet: its header differs from the first one',
    });
  }
  return t('boq.import_issue.mapping_format', {
    defaultValue: 'The column mapping was not used: it applies to spreadsheets only',
  });
}

/** An XPWE import note in the reader's language, or null to keep the server's wording. */
function xpweIssue(issue: ImportIssue, t: Translate, formatNumber: (value: number) => string): string | null {
  switch (issue.code) {
    case 'xpwe_quantity_mismatch':
      if (issue.computed == null || issue.declared == null) return null;
      return t('boq.import_issue.xpwe_quantity_mismatch', {
        defaultValue:
          'The measurement rows add up to {{computed}}, the file states {{declared}}. The measured quantity was imported',
        computed: formatNumber(issue.computed),
        declared: formatNumber(issue.declared),
      });
    case 'xpwe_see_item_flattened':
      if (issue.ref == null || issue.value == null) return null;
      return t('boq.import_issue.xpwe_see_item_flattened', {
        defaultValue: 'A row repeating the quantity of item {{ref}} was stored as its value, {{value}}',
        ref: issue.ref,
        value: formatNumber(issue.value),
      });
    case 'xpwe_see_item_unresolved':
      return t('boq.import_issue.xpwe_see_item_unresolved', {
        defaultValue: 'A row refers to item {{ref}}, which could not be read. It counts as zero',
        ref: issue.ref ?? '-',
      });
    case 'xpwe_expression_unreadable':
      return t('boq.import_issue.xpwe_expression_unreadable', {
        defaultValue: 'The measurement {{text}} could not be read and counts as zero',
        text: issue.text ?? '',
      });
    case 'xpwe_price_unreadable':
      return t('boq.import_issue.xpwe_price_unreadable', {
        defaultValue: 'The price {{text}} could not be read. The item was imported at zero',
        text: issue.text ?? '',
      });
    case 'xpwe_description_truncated':
      return t('boq.import_issue.xpwe_description_truncated', {
        defaultValue: 'The description was too long and was shortened. The full text is kept with the position',
      });
    case 'xpwe_encoding_fallback':
      return t('boq.import_issue.xpwe_encoding_fallback', {
        defaultValue: 'The file is not UTF-8 and was read as {{encoding}}',
        encoding: issue.encoding ?? '',
      });
    case 'xpwe_no_bill_items':
      return t('boq.import_issue.xpwe_no_bill_items', {
        defaultValue:
          'The file holds a price list and no measured bill (price-list items: {{count}}). Import it into a cost database instead',
        count: issue.count ?? 0,
      });
    case 'xpwe_more_warnings':
      return t('boq.import_issue.xpwe_more_warnings', {
        defaultValue: 'More warnings of the same kind, not listed: {{count}}',
        count: issue.count ?? 0,
      });
    case 'xpwe_price_item_missing':
      return t('boq.import_issue.xpwe_price_item_missing', {
        defaultValue: 'It refers to price-list item {{ref}}, which the file does not contain. It was not imported',
        ref: issue.ref || '-',
      });
    case 'xpwe_deductions_moved':
      if (issue.count == null || issue.amount == null) return null;
      return t('boq.import_issue.xpwe_deductions_moved', {
        defaultValue:
          "{{count}} items with a negative amount were imported without a price. Their {{amount}} is taken off by the deductions line among the bill's markups",
        count: issue.count,
        amount: formatNumber(Math.abs(issue.amount)),
      });
    case 'xpwe_signs_cancel':
      return t('boq.import_issue.xpwe_signs_cancel', {
        defaultValue:
          'Its quantity and unit rate are both negative, so it adds money. It was imported with both made positive',
      });
    case 'xpwe_price_out_of_range':
      return t('boq.import_issue.xpwe_price_out_of_range', {
        defaultValue: 'The unit rate {{text}} is outside the range a price can take. It was not imported',
        text: issue.text ?? '',
      });
    case 'xpwe_measurement_out_of_range':
      return t('boq.import_issue.xpwe_measurement_out_of_range', {
        defaultValue: 'A measurement row is larger than any real quantity and counts as zero',
      });
    case 'xpwe_quantity_out_of_range':
      return t('boq.import_issue.xpwe_quantity_out_of_range', {
        defaultValue: 'Its quantity is larger than any real one. It was not imported',
      });
    case 'xpwe_item_failed':
      return t('boq.import_issue.xpwe_item_failed', {
        defaultValue: 'Its numbers could not be worked out. It was not imported',
      });
    case 'xpwe_duplicate_item_id':
      return t('boq.import_issue.xpwe_duplicate_item_id', {
        defaultValue:
          'It has the same ID ({{ref}}) as item {{first}}. Both were imported; rows repeating item {{ref}} follow item {{first}}',
        ref: issue.ref ?? '-',
        first: issue.first ?? '-',
      });
    default:
      return null;
  }
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
  } else if (issue.code === 'comma_read_as_thousands' && issue.text != null && issue.value != null) {
    body = t('boq.import_issue.comma_thousands', {
      defaultValue: '{{text}} was read as {{value}}: the comma separates thousands',
      text: issue.text,
      value: formatNumber(issue.value),
    });
  } else if (issue.code === 'column_mapping_not_applied') {
    const where = issue.sheet
      ? `${t('boq.import_issue.sheet', { defaultValue: 'Sheet {{sheet}}', sheet: issue.sheet })}: `
      : '';
    return where + mappingNotApplied(issue, t);
  } else if (issue.code === 'header_not_recognised') {
    const where = issue.sheet
      ? `${t('boq.import_issue.sheet', { defaultValue: 'Sheet {{sheet}}', sheet: issue.sheet })}: `
      : '';
    return where + headerNotRecognised(issue, t);
  } else {
    body = xpweIssue(issue, t, formatNumber) ?? issue.message ?? issue.error ?? '';
  }
  return prefixOf(issue, t) + body;
}
