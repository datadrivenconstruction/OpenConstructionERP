// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Wording of the toast the BOQ editor shows once a file import lands.
 *
 * Counts are shown as "label: number" so no language has to agree a noun
 * with the number next to it. Total, tax and recap lines the importer left
 * out of the positions are counted on their own, so a user comparing the
 * bill with the file's own row count sees where the difference went.
 */

/** Minimal shape of the i18next `t` used here (repo convention). */
type Translate = (key: string, opts?: Record<string, unknown>) => string;

export interface ImportToastResult {
  imported: number;
  errors: unknown[];
  /** Round-trip imports: rows matched to an existing position and rewritten,
   *  matched and left as they were, and removed. ``imported`` counts only the
   *  rows created, so re-importing an exported bill has ``imported`` 0. */
  updated?: number;
  unchanged?: number;
  deleted?: number;
  total_items?: number;
  method?: string;
  model_used?: string | null;
  cad_elements?: number;
  skipped?: number;
  sections?: unknown[];
  source_format?: string;
  currency?: string;
  warnings?: { code?: string }[];
}

export function importToastText(
  result: ImportToastResult,
  isGaeb: boolean,
  t: Translate,
): { title: string; message?: string } {
  const ai = () => t('boq.import_toast.ai', { defaultValue: 'AI' });
  let method: string;
  if (isGaeb || result.source_format === 'gaeb') {
    const sections = Array.isArray(result.sections) ? result.sections.length : 0;
    method = t('boq.import_toast.method_gaeb', { defaultValue: 'GAEB XML, sections: {{count}}', count: sections });
    if (result.currency) method += `, ${result.currency}`;
  } else if (result.method === 'cad_ai') {
    method = t('boq.import_toast.method_cad', {
      defaultValue: 'CAD + {{model}}, elements: {{count}}',
      model: result.model_used ?? ai(),
      count: result.cad_elements ?? 0,
    });
  } else if (result.method === 'ai') {
    method = result.model_used
      ? t('boq.import_toast.method_ai', { defaultValue: 'AI: {{model}}', model: result.model_used })
      : ai();
  } else {
    method = t('boq.import_toast.method_direct', { defaultValue: 'direct' });
  }

  const parts: string[] = [];
  let title: string;
  if (isRoundTrip(result)) {
    // A re-import matches rows to the positions already there: counting only
    // the created ones read "0 of N" for a bill whose every row was updated.
    title = t('boq.import_toast.title_round_trip', {
      defaultValue: 'Items added: {{created}}, updated: {{updated}}, unchanged: {{unchanged}} ({{method}})',
      created: result.imported,
      updated: result.updated ?? 0,
      unchanged: result.unchanged ?? 0,
      method,
    });
    if ((result.deleted ?? 0) > 0) {
      parts.push(t('boq.import_toast.deleted', { defaultValue: 'Items removed: {{count}}', count: result.deleted }));
    }
  } else {
    // GAEB returns ``skipped`` instead of ``total_items``, so derive a
    // denominator that reads cleanly for both shapes.
    const total = result.total_items ?? result.imported + (result.skipped ?? 0);
    title = t('boq.import_toast.title', {
      defaultValue: 'Items imported: {{imported}} of {{total}} ({{method}})',
      imported: result.imported,
      total,
      method,
    });
  }

  const summaryRows = (result.warnings ?? []).filter((w) => w?.code === 'summary_row_skipped').length;
  if (summaryRows > 0) {
    parts.push(
      t('boq.import_toast.summary_skipped', {
        defaultValue: 'Total, tax or recap lines left out: {{count}}',
        count: summaryRows,
      }),
    );
  }
  if (result.errors.length > 0) {
    parts.push(t('boq.import_toast.errors', { defaultValue: 'Errors: {{count}}', count: result.errors.length }));
  }
  return { title, message: parts.length > 0 ? parts.join(' · ') : undefined };
}

function isRoundTrip(result: ImportToastResult): boolean {
  return (result.updated ?? 0) > 0 || (result.unchanged ?? 0) > 0 || (result.deleted ?? 0) > 0;
}

/** Whether the import changed or confirmed anything, for the toast's tone. */
export function importLanded(result: ImportToastResult): boolean {
  return result.imported > 0 || isRoundTrip(result);
}
