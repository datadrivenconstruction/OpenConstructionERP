// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure helpers that turn an estimate-audit's persisted per-row status into a
 * richer BOQ grid marker.
 *
 * The audit writes a compact summary onto `Position.metadata.audit`
 * (`{ status, groups, count }`) alongside `validation_status`. These helpers
 * read that summary so the grid can show, on hover, exactly which audit issues
 * a row carries - not just the generic error/warning dot. Kept free of React /
 * AG Grid so they are unit-testable.
 */

import { fmtList } from '@/shared/lib/formatters';

type TFn = (key: string, opts?: Record<string, unknown>) => string;

export interface AuditRowMeta {
  status?: string;
  groups: string[];
  count: number;
}

/** Read `metadata.audit` off a row's metadata, or null when absent/empty. */
export function readAuditMeta(metadata: unknown): AuditRowMeta | null {
  if (!metadata || typeof metadata !== 'object') return null;
  const audit = (metadata as Record<string, unknown>).audit;
  if (!audit || typeof audit !== 'object') return null;
  const a = audit as Record<string, unknown>;
  const groups = Array.isArray(a.groups)
    ? a.groups.filter((g): g is string => typeof g === 'string')
    : [];
  const count = typeof a.count === 'number' ? a.count : groups.length;
  if (count <= 0 && groups.length === 0) return null;
  const status = typeof a.status === 'string' ? a.status : undefined;
  return { status, groups, count };
}

const AUDIT_GROUP_LABELS: Record<string, { key: string; def: string }> = {
  missing_items: { key: 'boq.audit_group_missing_items', def: 'Missing items' },
  wrong_units: { key: 'boq.audit_group_wrong_units', def: 'Wrong units' },
  duplicates: { key: 'boq.audit_group_duplicates', def: 'Duplicates' },
  price_outliers: { key: 'boq.audit_group_price_outliers', def: 'Price outliers' },
};

/**
 * Rich hover text for a BOQ row, sourced from the persisted audit summary.
 * Returns `undefined` (no tooltip) when the row has no audit findings, so it
 * plugs straight into an AG Grid column `tooltipValueGetter`.
 */
export function auditRowTooltip(
  data: { metadata?: unknown } | undefined,
  t: TFn,
): string | undefined {
  const audit = data ? readAuditMeta(data.metadata) : null;
  if (!audit) return undefined;
  const labels = audit.groups.map((g) => {
    const entry = AUDIT_GROUP_LABELS[g];
    return entry ? t(entry.key, { defaultValue: entry.def }) : g.replace(/_/g, ' ');
  });
  return t('boq.audit_row_tooltip', {
    defaultValue: 'Estimate audit: {{count}} issue(s) - {{groups}}',
    count: audit.count,
    groups: fmtList(labels),
  });
}
