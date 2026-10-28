// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Translation keys for the two vocabularies the post-calculation API emits.
 *
 * The backend hands back stable data tokens (`on_plan`, `material`, ...) and
 * the key that names each one, deliberately carrying no locale of its own.
 * Both maps are written out key by key rather than assembled with a template,
 * so a scan for a key finds it as a literal string in the source. A key built
 * as `postcalc.status.${code}` is invisible to that scan, and a key nothing can
 * see is a key nothing keeps translated.
 */

import type { useTranslation } from 'react-i18next';

type Translate = ReturnType<typeof useTranslation>['t'];

/** Per-line productivity verdicts, from `postcalc.model.STATUS_I18N_KEYS`. */
export const STATUS_KEYS: Record<string, string> = {
  on_plan: 'postcalc.status.on_plan',
  under_productive: 'postcalc.status.under_productive',
  over_productive: 'postcalc.status.over_productive',
  no_baseline: 'postcalc.status.no_baseline',
  no_actuals: 'postcalc.status.no_actuals',
  no_progress: 'postcalc.status.no_progress',
};

/** Resource categories, the platform-wide `price_breakdown.kind.*` family. */
export const KIND_KEYS: Record<string, string> = {
  labor: 'price_breakdown.kind.labor',
  material: 'price_breakdown.kind.material',
  machinery: 'price_breakdown.kind.machinery',
  equipment: 'price_breakdown.kind.equipment',
  subcontractor: 'price_breakdown.kind.subcontractor',
  other: 'price_breakdown.kind.other',
};

/** Translate a status token, falling back to the raw token for an unknown one. */
export function statusLabel(code: string, t: Translate): string {
  const key = STATUS_KEYS[code];
  return key ? t(key) : code;
}

/** Translate a resource-category token, falling back to the label the API sent. */
export function kindLabel(code: string, fallback: string, t: Translate): string {
  const key = KIND_KEYS[code];
  return key ? t(key) : fallback || code;
}
