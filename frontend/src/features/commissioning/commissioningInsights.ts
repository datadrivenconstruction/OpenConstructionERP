// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Commissioning's contribution to the Module Insights panel. The systems list
 * shows a readiness light per row; what a commissioning manager needs before a
 * handover date is the aggregate - how ready the plant is overall, which
 * system types are dragging, where the outstanding functional checks sit, and
 * how many critical issues are still blocking sign-off.
 *
 * Built from the systems the page already loaded, so the panel costs no extra
 * request. Readiness figures come from the backend's `readiness` summary, the
 * same numbers the row's traffic light is drawn from; a system with no
 * checklists defined yet contributes no readiness percentage rather than a
 * misleading zero.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';
import type { CxSystem } from './api';

type Translate = ReturnType<typeof useTranslation>['t'];

function titleCase(code: string): string {
  return code.charAt(0).toUpperCase() + code.slice(1).replace(/_/g, ' ');
}

function typeLabel(code: string, t: Translate): string {
  return t(`commissioning.type_${code}`, { defaultValue: titleCase(code) });
}

function statusLabel(code: string, t: Translate): string {
  return t(`commissioning.status_${code}`, { defaultValue: titleCase(code) });
}

function readinessLabel(code: string, t: Translate): string {
  return t(`commissioning.insights.rl_${code}`, { defaultValue: titleCase(code) });
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  name: string;
  type: string;
  status: string;
  location: string;
  readiness: string;
  pct: number;
  open_checks: number;
  open_critical: number;
  commissioned: number;
}

function toRow(s: CxSystem, unset: string, notDefined: string, t: Translate): Row {
  const r = s.readiness;
  return {
    name: s.name ?? '',
    type: typeLabel(String(s.system_type), t),
    status: statusLabel(s.status, t),
    location: s.location?.trim() || unset,
    // A system with no checklists has no honest readiness rating, so it gets
    // its own bucket instead of being lumped in with the red ones.
    readiness: r?.defined ? readinessLabel(r.readiness_level, t) : notDefined,
    pct: r?.defined ? Math.round(r.readiness_pct) : 0,
    open_checks: r?.open_functional_items ?? 0,
    open_critical: r?.open_critical_issues ?? 0,
    commissioned: s.status === 'commissioned' ? 1 : 0,
  };
}

export interface CommissioningInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

/**
 * Build the commissioning dataset and its built-in charts.
 *
 * No currency anywhere: a commissioning system carries no money, so the panel
 * deliberately exposes no currency-formatted measure.
 */
export function buildCommissioningInsights(
  systems: CxSystem[],
  t: Translate,
): CommissioningInsights {
  const unset = t('commissioning.insights.no_location', { defaultValue: 'No location' });
  const notDefined = t('commissioning.insights.rl_undefined', { defaultValue: 'No checks defined' });

  const rows: Row[] = systems.map((s) => toRow(s, unset, notDefined, t));

  const dataset: InsightDataset = {
    id: 'systems',
    label: t('commissioning.insights.ds_systems', { defaultValue: 'Commissioning systems' }),
    currency: '',
    fields: [
      { key: 'name', label: t('commissioning.insights.f_name', { defaultValue: 'System' }), kind: 'dimension' },
      { key: 'type', label: t('commissioning.insights.f_type', { defaultValue: 'System type' }), kind: 'dimension' },
      { key: 'status', label: t('commissioning.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'location', label: t('commissioning.insights.f_location', { defaultValue: 'Location' }), kind: 'dimension' },
      { key: 'readiness', label: t('commissioning.insights.f_readiness', { defaultValue: 'Readiness rating' }), kind: 'dimension' },
      { key: 'pct', label: t('commissioning.insights.f_pct', { defaultValue: 'Readiness %' }), kind: 'measure', format: 'percent' },
      { key: 'open_checks', label: t('commissioning.insights.f_open_checks', { defaultValue: 'Open functional checks' }), kind: 'measure', format: 'number' },
      { key: 'open_critical', label: t('commissioning.insights.f_open_critical', { defaultValue: 'Open critical issues' }), kind: 'measure', format: 'number' },
      { key: 'commissioned', label: t('commissioning.insights.f_commissioned', { defaultValue: 'Commissioned' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'systems', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-systems', title: t('commissioning.insights.k_systems', { defaultValue: 'Systems' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-readiness', title: t('commissioning.insights.k_readiness', { defaultValue: 'Avg readiness' }), chart: 'kpi', measure: 'pct', agg: 'avg', color: 4 },
    { ...base, id: 'kpi-commissioned', title: t('commissioning.insights.k_commissioned', { defaultValue: 'Commissioned' }), chart: 'kpi', measure: 'commissioned', agg: 'sum', color: 5 },
    { ...base, id: 'kpi-critical', title: t('commissioning.insights.k_critical', { defaultValue: 'Open critical issues' }), chart: 'kpi', measure: 'open_critical', agg: 'sum', color: 1 },
    { ...base, id: 'bar-readiness-by-type', title: t('commissioning.insights.c_readiness_by_type', { defaultValue: 'Readiness by system type' }), chart: 'bar', dimension: 'type', measure: 'pct', agg: 'avg', color: 4 },
    { ...base, id: 'donut-by-status', title: t('commissioning.insights.c_by_status', { defaultValue: 'Systems by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 0 },
    { ...base, id: 'bar-checks-by-location', title: t('commissioning.insights.c_checks_by_location', { defaultValue: 'Outstanding checks by location' }), chart: 'bar', dimension: 'location', measure: 'open_checks', agg: 'sum', color: 1 },
    { ...base, id: 'donut-by-readiness', title: t('commissioning.insights.c_by_readiness', { defaultValue: 'Systems by readiness rating' }), chart: 'donut', dimension: 'readiness', agg: 'count', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
