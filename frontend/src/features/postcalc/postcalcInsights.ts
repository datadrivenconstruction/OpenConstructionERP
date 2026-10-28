// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Post-calculation's contribution to the Module Insights panel. It charts the
 * report the page has already loaded, client-side, with no second request.
 *
 * One dataset, the per-line reconciliation, because every figure worth charting
 * hangs off a BoQ line: the hours the estimate budgeted for what was installed
 * against the hours booked, and the material money it allowed against what the
 * store consumed. Money is genuine here (the report states a project currency
 * and every cost is in it), hours and the productivity factor are plain
 * numbers, and the status dimension reuses the same `postcalc.status.*` keys
 * the table's badges use so a slice reads exactly like the row it came from.
 *
 * Lines the site could not price the material of contribute a zero to the
 * material measures rather than being dropped, and the dedicated "priced"
 * measure counts how many of them there were - so a chart built mostly from
 * unmetered lines can be recognised as one instead of being read as a saving.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';
import type { ProductivityLine } from './api';
import { statusLabel } from './labels';

type Translate = ReturnType<typeof useTranslation>['t'];

/** Coerce a decimal-as-string cell to a finite number (0 when absent). */
function toNum(v: string | null | undefined): number {
  if (v === null || v === undefined || v === '') return 0;
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

interface LineRow {
  // Index signature so a row is directly a valid InsightDataset row.
  [key: string]: string | number;
  ref: string;
  unit: string;
  status: string;
  earned_hours: number;
  actual_hours: number;
  hours_variance: number;
  factor: number;
  labour_variance: number;
  material_earned: number;
  material_actual: number;
  material_variance: number;
  material_priced: number;
}

function toRow(line: ProductivityLine, label: (code: string) => string, noUnit: string): LineRow {
  const priced = line.actual_material_cost !== null;
  return {
    ref: (line.ref || '').trim() || (line.description || '').trim().slice(0, 40),
    unit: (line.unit || '').trim() || noUnit,
    status: label(line.status),
    earned_hours: toNum(line.earned_hours),
    actual_hours: toNum(line.actual_hours),
    hours_variance: toNum(line.hours_variance),
    factor: toNum(line.productivity_factor),
    labour_variance: toNum(line.labour_cost_variance_earned),
    material_earned: priced ? toNum(line.earned_material_cost) : 0,
    material_actual: priced ? toNum(line.actual_material_cost) : 0,
    material_variance: priced ? toNum(line.material_cost_variance_earned) : 0,
    material_priced: priced ? 1 : 0,
  };
}

export interface PostCalcInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildPostCalcInsights(
  lines: ProductivityLine[],
  currency: string,
  t: Translate,
): PostCalcInsights {
  const noUnit = t('postcalc.insights.no_unit');
  const rows = lines.map((line) => toRow(line, (code) => statusLabel(code, t), noUnit));

  const dataset: InsightDataset = {
    id: 'lines',
    label: t('postcalc.insights.ds_lines'),
    currency: currency || '',
    fields: [
      { key: 'ref', label: t('postcalc.insights.f_ref'), kind: 'dimension' },
      { key: 'unit', label: t('postcalc.insights.f_unit'), kind: 'dimension' },
      { key: 'status', label: t('postcalc.insights.f_status'), kind: 'dimension' },
      { key: 'earned_hours', label: t('postcalc.insights.f_earned_hours'), kind: 'measure', format: 'number' },
      { key: 'actual_hours', label: t('postcalc.insights.f_actual_hours'), kind: 'measure', format: 'number' },
      { key: 'hours_variance', label: t('postcalc.insights.f_hours_variance'), kind: 'measure', format: 'number' },
      { key: 'factor', label: t('postcalc.insights.f_factor'), kind: 'measure', format: 'number' },
      { key: 'labour_variance', label: t('postcalc.insights.f_labour_variance'), kind: 'measure', format: 'currency' },
      { key: 'material_earned', label: t('postcalc.insights.f_material_earned'), kind: 'measure', format: 'currency' },
      { key: 'material_actual', label: t('postcalc.insights.f_material_actual'), kind: 'measure', format: 'currency' },
      { key: 'material_variance', label: t('postcalc.insights.f_material_variance'), kind: 'measure', format: 'currency' },
      { key: 'material_priced', label: t('postcalc.insights.f_material_priced'), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'lines', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-lines', title: t('postcalc.insights.k_lines'), chart: 'kpi', agg: 'count', color: 0 },
    {
      ...base,
      id: 'kpi-hours-variance',
      title: t('postcalc.insights.k_hours_variance'),
      chart: 'kpi',
      measure: 'hours_variance',
      agg: 'sum',
      color: 1,
    },
    {
      ...base,
      id: 'kpi-material-variance',
      title: t('postcalc.insights.k_material_variance'),
      chart: 'kpi',
      measure: 'material_variance',
      agg: 'sum',
      color: 4,
    },
    {
      ...base,
      id: 'kpi-material-priced',
      title: t('postcalc.insights.k_material_priced'),
      chart: 'kpi',
      measure: 'material_priced',
      agg: 'sum',
      color: 5,
    },
    {
      ...base,
      id: 'donut-status',
      title: t('postcalc.insights.c_by_status'),
      chart: 'donut',
      dimension: 'status',
      agg: 'count',
      color: 1,
    },
    {
      ...base,
      id: 'bar-hours-by-ref',
      title: t('postcalc.insights.c_hours_by_ref'),
      chart: 'bar',
      dimension: 'ref',
      measure: 'hours_variance',
      agg: 'sum',
      color: 2,
    },
    {
      ...base,
      id: 'bar-material-by-ref',
      title: t('postcalc.insights.c_material_by_ref'),
      chart: 'bar',
      dimension: 'ref',
      measure: 'material_variance',
      agg: 'sum',
      color: 4,
    },
  ];

  return { datasets: [dataset], builtins };
}
