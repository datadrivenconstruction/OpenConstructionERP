// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Prefab's contribution to the Module Insights panel.
 *
 * Off-site manufacture goes wrong in two ways: units sit in one stage longer
 * than the programme allows, and the value tied up in production stops
 * matching what has actually been installed. The unit list shows one row per
 * unit; this panel shows where the fleet is as a whole - how many units sit in
 * each stage, how much earned value each stage is carrying, and which units
 * have already sailed past the date they were meant to be installed.
 *
 * Unlike most registers, prefab units carry real money: `cost_basis` comes
 * from the linked BOQ position or assembly, and `earned_value` is that basis
 * times the stage machine's completed fraction. So this is one of the few
 * modules where a currency-formatted measure is honest.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';
import type { PrefabUnit } from './api';

type Translate = ReturnType<typeof useTranslation>['t'];

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function titleCase(code: string): string {
  return code.charAt(0).toUpperCase() + code.slice(1).replace(/_/g, ' ');
}

function stageLabel(code: string, t: Translate): string {
  return t(`prefab.stage_${code}`, { defaultValue: titleCase(code) });
}

function typeLabel(code: string, t: Translate): string {
  return t(`prefab.type_${code}`, { defaultValue: titleCase(code) });
}

/** Decimal strings from the API must never poison a sum. */
function toNumber(value: string | number | null | undefined): number {
  const n = typeof value === 'number' ? value : Number.parseFloat(String(value ?? ''));
  return Number.isFinite(n) ? n : 0;
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  ref: string;
  type: string;
  stage: string;
  target_month: string;
  basis: number;
  earned: number;
  progress: number;
  late: number;
  installed: number;
}

function toRow(u: PrefabUnit, t: Translate): Row {
  const installed = u.status === 'installed';
  const target = u.target_install_date ? new Date(u.target_install_date).getTime() : NaN;
  return {
    ref: u.ref ?? '',
    type: typeLabel(String(u.unit_type), t),
    stage: stageLabel(String(u.status), t),
    target_month: monthKey(u.target_install_date),
    basis: toNumber(u.cost_basis),
    earned: toNumber(u.earned_value),
    // completed_fraction is 0..1 from the stage machine; the panel's percent
    // format expects 0..100.
    progress: Math.round((u.completed_fraction ?? 0) * 100),
    // Only work still outstanding can be late. A unit already installed is
    // history, not something to chase.
    late: !installed && !Number.isNaN(target) && target < Date.now() ? 1 : 0,
    installed: installed ? 1 : 0,
  };
}

export interface PrefabInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

/**
 * Build the prefab dataset and its built-in charts. `currency` is the
 * project's currency and is genuinely used here - see the file header.
 */
export function buildPrefabInsights(
  units: PrefabUnit[],
  currency: string,
  t: Translate,
): PrefabInsights {
  const rows: Row[] = units.map((u) => toRow(u, t));

  const dataset: InsightDataset = {
    id: 'units',
    label: t('prefab.insights.ds_units', { defaultValue: 'Prefab units' }),
    currency: currency || '',
    fields: [
      { key: 'ref', label: t('prefab.insights.f_ref', { defaultValue: 'Unit' }), kind: 'dimension' },
      { key: 'type', label: t('prefab.insights.f_type', { defaultValue: 'Unit type' }), kind: 'dimension' },
      { key: 'stage', label: t('prefab.insights.f_stage', { defaultValue: 'Stage' }), kind: 'dimension' },
      { key: 'target_month', label: t('prefab.insights.f_target_month', { defaultValue: 'Target install month' }), kind: 'dimension' },
      { key: 'basis', label: t('prefab.insights.f_basis', { defaultValue: 'Cost basis' }), kind: 'measure', format: 'currency' },
      { key: 'earned', label: t('prefab.insights.f_earned', { defaultValue: 'Earned value' }), kind: 'measure', format: 'currency' },
      { key: 'progress', label: t('prefab.insights.f_progress', { defaultValue: 'Production progress' }), kind: 'measure', format: 'percent' },
      { key: 'late', label: t('prefab.insights.f_late', { defaultValue: 'Past target install date' }), kind: 'measure', format: 'number' },
      { key: 'installed', label: t('prefab.insights.f_installed', { defaultValue: 'Installed' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'units', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-units', title: t('prefab.insights.k_units', { defaultValue: 'Units' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-earned', title: t('prefab.insights.k_earned', { defaultValue: 'Earned value' }), chart: 'kpi', measure: 'earned', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-progress', title: t('prefab.insights.k_progress', { defaultValue: 'Avg production progress' }), chart: 'kpi', measure: 'progress', agg: 'avg', color: 4 },
    { ...base, id: 'kpi-late', title: t('prefab.insights.k_late', { defaultValue: 'Past target install date' }), chart: 'kpi', measure: 'late', agg: 'sum', color: 5 },
    { ...base, id: 'donut-by-stage', title: t('prefab.insights.c_by_stage', { defaultValue: 'Units by stage' }), chart: 'donut', dimension: 'stage', agg: 'count', color: 0 },
    { ...base, id: 'bar-earned-by-stage', title: t('prefab.insights.c_earned_by_stage', { defaultValue: 'Earned value by stage' }), chart: 'bar', dimension: 'stage', measure: 'earned', agg: 'sum', color: 1 },
    { ...base, id: 'bar-by-type', title: t('prefab.insights.c_by_type', { defaultValue: 'Units by type' }), chart: 'bar', dimension: 'type', agg: 'count', color: 4 },
    { ...base, id: 'area-due-by-month', title: t('prefab.insights.c_due_by_month', { defaultValue: 'Units due to install by month' }), chart: 'area', dimension: 'target_month', agg: 'count', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
