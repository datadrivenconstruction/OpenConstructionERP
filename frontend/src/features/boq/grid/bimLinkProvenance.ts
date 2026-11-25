// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { TFunction } from 'i18next';

/** Provenance the backend writes to ``metadata.bim_link_quantity`` on every link sync. */
export interface BimLinkQuantityRecord {
  status?: 'ok' | 'no_quantity' | 'unit_unsupported' | string;
  method?: 'count' | 'sum' | 'none' | string;
  formula?: string;
  quantity?: string | null;
  applied_quantity?: string | null;
  model_quantity?: string | null;
  manual_kept?: boolean;
  element_count?: number;
  contributing?: number;
  missing_count?: number;
  unit?: string;
  models?: { model_id: string; name: string | null; version: string | null; elements: number }[];
}

export type BimLinkState = 'model' | 'manual_kept' | 'no_quantity' | null;

export function readBimLinkRecord(meta: Record<string, unknown> | null | undefined): BimLinkQuantityRecord | null {
  const raw = meta?.bim_link_quantity;
  return raw && typeof raw === 'object' ? (raw as BimLinkQuantityRecord) : null;
}

/** Which treatment the quantity cell gives a model-linked position. */
export function bimLinkState(rec: BimLinkQuantityRecord | null): BimLinkState {
  if (!rec) return null;
  if (rec.manual_kept) return 'manual_kept';
  if (rec.status === 'no_quantity' || rec.status === 'unit_unsupported') return 'no_quantity';
  return rec.applied_quantity != null ? 'model' : null;
}

/** Multi-line tooltip: model and version, elements, formula, and what the user should know. */
export function bimLinkTooltip(rec: BimLinkQuantityRecord, t: TFunction): string {
  const lines: string[] = [];
  for (const m of rec.models ?? []) {
    lines.push(
      t('boq.bim_prov_model', {
        defaultValue: 'Model {{name}} v{{version}}, elements: {{count}}',
        name: m.name ?? m.model_id,
        version: m.version ?? '-',
        count: m.elements,
      }),
    );
  }
  if (rec.formula) lines.push(t('boq.bim_prov_formula', { defaultValue: 'Formula: {{formula}}', formula: rec.formula }));
  if (rec.missing_count) {
    lines.push(
      t('boq.bim_prov_missing', {
        defaultValue: 'Linked elements without a value in this unit (they add nothing): {{count}}',
        count: rec.missing_count,
      }),
    );
  }
  const state = bimLinkState(rec);
  if (state === 'manual_kept') {
    lines.push(
      t('boq.bim_prov_manual_kept', {
        defaultValue: 'Your quantity is kept. The model gives {{quantity}}.',
        quantity: rec.model_quantity ?? '-',
      }),
    );
  } else if (state === 'no_quantity') {
    lines.push(
      t('boq.bim_prov_no_quantity', {
        defaultValue: 'The model has no value in {{unit}} for these elements, so the quantity was not changed.',
        unit: rec.unit ?? '',
      }),
    );
  }
  return lines.join('\n');
}
