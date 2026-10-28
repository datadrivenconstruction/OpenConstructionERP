// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Field Time's contribution to the Module Insights panel.
 *
 * The KPI band above the list already answers "how many timesheets and how
 * many hours". What it cannot answer, and what a quantity surveyor asks every
 * valuation, is where those hours landed: which cost codes are absorbing them,
 * how much of the week was daywork rather than measured work, and how many
 * hours are still sitting unapproved. So this dataset is built at LINE level,
 * not sheet level - one row per booked line, carrying its sheet's date and
 * status down onto it.
 *
 * Daywork matters most. Daywork hours are the ones recovered against a
 * variation rather than the bill, so a week where daywork quietly grows is a
 * week where the final account is drifting.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';
import type { FieldTimesheet } from './api';

type Translate = ReturnType<typeof useTranslation>['t'];

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function titleCase(code: string): string {
  return code.charAt(0).toUpperCase() + code.slice(1).replace(/_/g, ' ');
}

function statusLabel(code: string, t: Translate): string {
  return t(`field_time.status_${code}`, { defaultValue: titleCase(code) });
}

function kindLabel(code: string, t: Translate): string {
  return t(`field_time.insights.kind_${code}`, { defaultValue: titleCase(code) });
}

/** Hours arrive as decimal strings from the API; a bad value must not poison a sum. */
function toHours(value: string | number | null | undefined): number {
  const n = typeof value === 'number' ? value : Number.parseFloat(String(value ?? ''));
  return Number.isFinite(n) ? n : 0;
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  reference: string;
  month: string;
  status: string;
  cost_code: string;
  kind: string;
  daywork_flag: string;
  hours: number;
  daywork: number;
  unapproved: number;
}

export interface FieldTimeInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

interface Labels {
  noCode: string;
  yes: string;
  no: string;
}

function toRows(sheets: FieldTimesheet[], labels: Labels, t: Translate): Row[] {
  const rows: Row[] = [];
  for (const sheet of sheets) {
    const month = monthKey(sheet.date);
    const status = statusLabel(sheet.status, t);
    // Anything not yet approved is hours the project has spent but not agreed.
    // Reversed sheets are excluded - they exist to cancel, not to claim.
    const pendingApproval = sheet.status === 'draft' || sheet.status === 'submitted';
    for (const line of sheet.lines ?? []) {
      const hours = toHours(line.hours);
      rows.push({
        reference: sheet.reference ?? '',
        month,
        status,
        cost_code: line.cost_code?.trim() || labels.noCode,
        kind: kindLabel(line.kind, t),
        daywork_flag: line.is_daywork ? labels.yes : labels.no,
        hours,
        daywork: line.is_daywork ? hours : 0,
        unapproved: pendingApproval ? hours : 0,
      });
    }
  }
  return rows;
}

/**
 * Build the field time dataset and its built-in charts.
 *
 * Hours, not money: a timesheet line carries no rate, so the panel exposes no
 * currency-formatted measure and passes an empty currency.
 */
export function buildFieldTimeInsights(sheets: FieldTimesheet[], t: Translate): FieldTimeInsights {
  const labels: Labels = {
    noCode: t('field_time.insights.no_cost_code', { defaultValue: 'No cost code' }),
    yes: t('field_time.insights.daywork_yes', { defaultValue: 'Daywork' }),
    no: t('field_time.insights.daywork_no', { defaultValue: 'Measured work' }),
  };

  // Sheets with no booked lines contribute nothing, so a project that has only
  // empty sheets ends up with an empty dataset rather than an invented one.
  const rows = toRows(sheets, labels, t);

  const dataset: InsightDataset = {
    id: 'lines',
    label: t('field_time.insights.ds_lines', { defaultValue: 'Booked time' }),
    currency: '',
    fields: [
      { key: 'reference', label: t('field_time.insights.f_reference', { defaultValue: 'Timesheet' }), kind: 'dimension' },
      { key: 'month', label: t('field_time.insights.f_month', { defaultValue: 'Month' }), kind: 'dimension' },
      { key: 'status', label: t('field_time.insights.f_status', { defaultValue: 'Sheet status' }), kind: 'dimension' },
      { key: 'cost_code', label: t('field_time.insights.f_cost_code', { defaultValue: 'Cost code' }), kind: 'dimension' },
      { key: 'kind', label: t('field_time.insights.f_kind', { defaultValue: 'Labour or plant' }), kind: 'dimension' },
      { key: 'daywork_flag', label: t('field_time.insights.f_daywork_flag', { defaultValue: 'Basis' }), kind: 'dimension' },
      { key: 'hours', label: t('field_time.insights.f_hours', { defaultValue: 'Hours' }), kind: 'measure', format: 'number' },
      { key: 'daywork', label: t('field_time.insights.f_daywork', { defaultValue: 'Daywork hours' }), kind: 'measure', format: 'number' },
      { key: 'unapproved', label: t('field_time.insights.f_unapproved', { defaultValue: 'Unapproved hours' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'lines', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-hours', title: t('field_time.insights.k_hours', { defaultValue: 'Hours booked' }), chart: 'kpi', measure: 'hours', agg: 'sum', color: 0 },
    { ...base, id: 'kpi-daywork', title: t('field_time.insights.k_daywork', { defaultValue: 'Daywork hours' }), chart: 'kpi', measure: 'daywork', agg: 'sum', color: 1 },
    // "Not yet approved", not "awaiting approval". This sums drafts as well as
    // submitted sheets, and a draft is not awaiting anything - nobody has been
    // asked to act on it. The KPI band above counts submitted sheets under the
    // awaiting label, so the two must not share a word they mean differently.
    { ...base, id: 'kpi-unapproved', title: t('field_time.insights.k_unapproved', { defaultValue: 'Hours not yet approved' }), chart: 'kpi', measure: 'unapproved', agg: 'sum', color: 4 },
    { ...base, id: 'kpi-lines', title: t('field_time.insights.k_lines', { defaultValue: 'Lines booked' }), chart: 'kpi', agg: 'count', color: 5 },
    { ...base, id: 'bar-by-cost-code', title: t('field_time.insights.c_by_cost_code', { defaultValue: 'Hours by cost code' }), chart: 'bar', dimension: 'cost_code', measure: 'hours', agg: 'sum', color: 0 },
    { ...base, id: 'donut-by-kind', title: t('field_time.insights.c_by_kind', { defaultValue: 'Labour against plant' }), chart: 'donut', dimension: 'kind', measure: 'hours', agg: 'sum', color: 4 },
    { ...base, id: 'bar-daywork-by-code', title: t('field_time.insights.c_daywork_by_code', { defaultValue: 'Daywork hours by cost code' }), chart: 'bar', dimension: 'cost_code', measure: 'daywork', agg: 'sum', color: 1 },
    { ...base, id: 'area-over-time', title: t('field_time.insights.c_over_time', { defaultValue: 'Hours booked over time' }), chart: 'area', dimension: 'month', measure: 'hours', agg: 'sum', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
