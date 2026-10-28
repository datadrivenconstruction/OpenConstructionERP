// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Wording and filtering of exchange fidelity items.
 *
 * Every kind and field the server sends is a code; the reader sees it in
 * their own language through the keys below. An unknown code is shown as it
 * came rather than dropped, so a newer server never hides a loss.
 */
import type { FidelityItem, FidelityReport, FidelitySeverity } from './exchangeFidelityApi';

type Translate = (key: string, opts?: Record<string, unknown>) => string;

export function severityLabel(t: Translate, severity: string): string {
  switch (severity) {
    case 'error':
      return t('boq.fidelity.severity_error', { defaultValue: 'Critical' });
    case 'warning':
      return t('boq.fidelity.severity_warning', { defaultValue: 'Warning' });
    case 'info':
      return t('boq.fidelity.severity_info', { defaultValue: 'Note' });
    default:
      return severity;
  }
}

export function kindLabel(t: Translate, kind: string): string {
  switch (kind) {
    case 'unsupported_element':
      return t('boq.fidelity.kind_unsupported_element', { defaultValue: 'Element not supported' });
    case 'truncated_text':
      return t('boq.fidelity.kind_truncated_text', { defaultValue: 'Text truncated' });
    case 'altered_text':
      return t('boq.fidelity.kind_altered_text', { defaultValue: 'Text altered' });
    case 'rounded_value':
      return t('boq.fidelity.kind_rounded_value', { defaultValue: 'Value rounded' });
    case 'value_out_of_range':
      return t('boq.fidelity.kind_value_out_of_range', { defaultValue: 'Value out of range' });
    case 'dropped_attribute':
      return t('boq.fidelity.kind_dropped_attribute', { defaultValue: 'Attribute dropped' });
    case 'unmapped_unit':
      return t('boq.fidelity.kind_unmapped_unit', { defaultValue: 'Unit not mapped' });
    case 'lost_hierarchy':
      return t('boq.fidelity.kind_lost_hierarchy', { defaultValue: 'Hierarchy level lost' });
    case 'markup_not_representable':
      return t('boq.fidelity.kind_markup_not_representable', { defaultValue: 'Markup not representable' });
    case 'attachment_skipped':
      return t('boq.fidelity.kind_attachment_skipped', { defaultValue: 'Attachment skipped' });
    case 'changed_identifier':
      return t('boq.fidelity.kind_changed_identifier', { defaultValue: 'Identifier changed' });
    case 'exceeds_limit':
      return t('boq.fidelity.kind_exceeds_limit', { defaultValue: 'Exceeds storage limit' });
    case 'rejected_row':
      return t('boq.fidelity.kind_rejected_row', { defaultValue: 'Row rejected' });
    case 'skipped_row':
      return t('boq.fidelity.kind_skipped_row', { defaultValue: 'Row skipped' });
    case 'parser_warning':
      return t('boq.fidelity.kind_parser_warning', { defaultValue: 'Reader warning' });
    case 'roundtrip_mismatch':
      return t('boq.fidelity.kind_roundtrip_mismatch', { defaultValue: 'Round-trip mismatch' });
    default:
      return kind;
  }
}

export function fieldLabel(t: Translate, field: string): string {
  switch (field) {
    case 'description':
      return t('boq.fidelity.field_description', { defaultValue: 'Description' });
    case 'long_text':
      return t('boq.fidelity.field_long_text', { defaultValue: 'Long text' });
    case 'unit':
      return t('boq.fidelity.field_unit', { defaultValue: 'Unit' });
    case 'quantity':
      return t('boq.fidelity.field_quantity', { defaultValue: 'Quantity' });
    case 'unit_rate':
      return t('boq.fidelity.field_unit_rate', { defaultValue: 'Unit rate' });
    case 'total':
      return t('boq.fidelity.field_total', { defaultValue: 'Total' });
    case 'ordinal':
      return t('boq.fidelity.field_ordinal', { defaultValue: 'Position number' });
    case 'markup':
      return t('boq.fidelity.field_markup', { defaultValue: 'Markup' });
    case 'resources':
      return t('boq.fidelity.field_resources', { defaultValue: 'Resources' });
    case 'classification':
      return t('boq.fidelity.field_classification', { defaultValue: 'Classification' });
    case 'hierarchy':
      return t('boq.fidelity.field_hierarchy', { defaultValue: 'Hierarchy' });
    case 'attachment':
      return t('boq.fidelity.field_attachment', { defaultValue: 'Attachment' });
    case 'row':
      return t('boq.fidelity.field_row', { defaultValue: 'Row' });
    case 'column':
      return t('boq.fidelity.field_column', { defaultValue: 'Column' });
    case 'currency':
      return t('boq.fidelity.field_currency', { defaultValue: 'Currency' });
    case 'metadata':
      return t('boq.fidelity.field_metadata', { defaultValue: 'Metadata' });
    case 'boq.name':
      return t('boq.fidelity.field_boq_name', { defaultValue: 'Bill name' });
    case 'project.name':
      return t('boq.fidelity.field_project_name', { defaultValue: 'Project name' });
    case 'file':
      return t('boq.fidelity.field_file', { defaultValue: 'File' });
    default:
      // Element and record names of the format itself (CtlgAssign, ~G) are shown as written.
      return field;
  }
}

/** Format names as the export menu shows them. */
export function formatLabel(t: Translate, formatId: string, variant = ''): string {
  switch (formatId) {
    case 'gaeb_xml':
      return variant ? `GAEB DA XML ${variant.toUpperCase()}` : 'GAEB DA XML';
    case 'bc3':
      return 'BC3 (FIEBDC-3)';
    case 'excel':
      return t('boq.fidelity.format_excel', { defaultValue: 'Excel' });
    case 'csv':
      return 'CSV';
    case 'xpwe':
      return 'XPWE';
    default:
      return formatId;
  }
}

export interface FidelityFilter {
  severity: FidelitySeverity | '';
  kind: string;
  query: string;
}

export const EMPTY_FILTER: FidelityFilter = { severity: '', kind: '', query: '' };

/** The items the filter keeps; the text search looks at position, field and both values. */
export function filterFidelityItems(items: FidelityItem[], filter: FidelityFilter): FidelityItem[] {
  const query = filter.query.trim().toLocaleLowerCase();
  return items.filter((item) => {
    if (filter.severity && item.severity !== filter.severity) return false;
    if (filter.kind && item.kind !== filter.kind) return false;
    if (!query) return true;
    return [item.position_ref, item.field, item.original ?? '', item.written ?? '', item.detail]
      .some((value) => value.toLocaleLowerCase().includes(query));
  });
}

/** Kinds present in a report, most frequent first, for the kind filter. */
export function kindsInReport(report: FidelityReport): string[] {
  return Object.entries(report.summary.by_kind ?? {})
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([kind]) => kind);
}

/** Whether a report is worth interrupting the reader for after an export or import. */
export function needsAttention(summary: Pick<FidelityReport['summary'], 'by_severity'> | null | undefined): boolean {
  if (!summary) return false;
  return (summary.by_severity.error ?? 0) + (summary.by_severity.warning ?? 0) > 0;
}
