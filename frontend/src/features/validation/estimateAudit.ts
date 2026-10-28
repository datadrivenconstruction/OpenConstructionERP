// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure types + helpers for the one-click estimate audit.
 *
 * Mirrors the backend `app.modules.validation.audit` contract: grouped findings
 * over a finished BOQ, each with an optional concrete fix, plus the quality
 * score used to show a re-run delta. Kept free of React so it is unit-testable.
 */

type TFn = (key: string, opts?: Record<string, unknown>) => string;

export type AuditFixType =
  | 'set_rate_to_median'
  | 'switch_unit'
  | 'merge_duplicate'
  | 'add_companion_line';

export interface AuditFix {
  type: AuditFixType;
  params: Record<string, unknown>;
}

export interface AuditFinding {
  id: string;
  group: string;
  rule_id: string;
  severity: string;
  message: string;
  ordinal: string;
  description: string;
  position_id: string | null;
  position_ids: string[];
  fix: AuditFix | null;
}

export interface AuditGroupSummary {
  key: string;
  count: number;
  severity: string;
}

export interface EstimateAuditResponse {
  report_id: string;
  boq_id: string;
  status: string;
  score: number | null;
  total_rules: number;
  passed_count: number;
  warning_count: number;
  error_count: number;
  info_count: number;
  rule_sets: string[];
  duration_ms: number;
  findings: AuditFinding[];
  groups: AuditGroupSummary[];
}

/** Body for POST /v1/boq/boqs/{boqId}/audit/apply-fix/. */
export interface ApplyFixBody {
  fix_type: AuditFixType;
  position_id?: string | null;
  params: Record<string, unknown>;
}

/** Stable display order for the grouped findings panel. */
export const AUDIT_GROUP_ORDER = [
  'missing_items',
  'wrong_units',
  'duplicates',
  'price_outliers',
] as const;

/**
 * Group findings by their `group`, returned in {@link AUDIT_GROUP_ORDER} so the
 * panel is stable across runs. Unknown groups are appended in first-seen order.
 */
export function groupFindings(findings: AuditFinding[]): Array<[string, AuditFinding[]]> {
  const buckets = new Map<string, AuditFinding[]>();
  for (const finding of findings) {
    const list = buckets.get(finding.group);
    if (list) list.push(finding);
    else buckets.set(finding.group, [finding]);
  }
  const ordered: Array<[string, AuditFinding[]]> = [];
  for (const key of AUDIT_GROUP_ORDER) {
    const list = buckets.get(key);
    if (list) {
      ordered.push([key, list]);
      buckets.delete(key);
    }
  }
  for (const [key, list] of buckets) ordered.push([key, list]);
  return ordered;
}

/** Convert a 0..1 score to an integer percentage (null → 0). */
export function scoreToPct(score: number | null | undefined): number {
  if (score == null || Number.isNaN(score)) return 0;
  return Math.round(Math.max(0, Math.min(1, score)) * 100);
}

export interface ScoreDelta {
  prevPct: number;
  nextPct: number;
  deltaPct: number;
  improved: boolean;
}

/** Percentage-point change between two 0..1 scores (before → after a fix). */
export function computeScoreDelta(prev: number | null, next: number | null): ScoreDelta {
  const prevPct = scoreToPct(prev);
  const nextPct = scoreToPct(next);
  const deltaPct = nextPct - prevPct;
  return { prevPct, nextPct, deltaPct, improved: deltaPct > 0 };
}

/** Human label for a finding group (i18n, with English default). */
export function groupLabel(key: string, t: TFn): string {
  const map: Record<string, { key: string; def: string }> = {
    missing_items: { key: 'validation.audit_group_missing_items', def: 'Missing items' },
    wrong_units: { key: 'validation.audit_group_wrong_units', def: 'Wrong units' },
    duplicates: { key: 'validation.audit_group_duplicates', def: 'Duplicates' },
    price_outliers: { key: 'validation.audit_group_price_outliers', def: 'Price outliers' },
  };
  const entry = map[key];
  return entry ? t(entry.key, { defaultValue: entry.def }) : key.replace(/_/g, ' ');
}

/**
 * Short, human action label for a fix - includes the concrete target value
 * (rate / unit) so the estimator sees exactly what one click will do.
 */
export function fixLabel(fix: AuditFix, t: TFn): string {
  switch (fix.type) {
    case 'set_rate_to_median':
      return t('validation.audit_fix_set_rate', {
        defaultValue: 'Set rate to {{rate}}',
        rate: String(fix.params.unit_rate ?? ''),
      });
    case 'switch_unit':
      return t('validation.audit_fix_switch_unit', {
        defaultValue: 'Set unit to {{unit}}',
        unit: String(fix.params.unit ?? ''),
      });
    case 'merge_duplicate': {
      const count = Array.isArray(fix.params.duplicate_position_ids)
        ? fix.params.duplicate_position_ids.length
        : 1;
      return t('validation.audit_fix_merge_duplicate', {
        defaultValue: 'Renumber duplicate ({{count}})',
        count,
      });
    }
    case 'add_companion_line':
      return t('validation.audit_fix_add_companion', {
        defaultValue: 'Add a line to this section',
      });
    default:
      return t('validation.audit_fix_generic', { defaultValue: 'Apply fix' });
  }
}

/** Build the apply-fix request body from a finding's fix descriptor. */
export function toApplyFixBody(finding: AuditFinding): ApplyFixBody | null {
  if (!finding.fix) return null;
  return {
    fix_type: finding.fix.type,
    position_id: finding.position_id,
    params: finding.fix.params,
  };
}
