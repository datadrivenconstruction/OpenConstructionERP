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

  // GAEB returns ``skipped`` instead of ``total_items``, so derive a
  // denominator that reads cleanly for both shapes.
  const total = result.total_items ?? result.imported + (result.skipped ?? 0);
  const title = t('boq.import_toast.title', {
    defaultValue: 'Items imported: {{imported}} of {{total}} ({{method}})',
    imported: result.imported,
    total,
    method,
  });

  const parts: string[] = [];
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
