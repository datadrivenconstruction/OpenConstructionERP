// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * CVR's contribution to the Module Insights panel.
 *
 * The CVR page's namesake register - the monthly CVR reports keyed
 * ['cvr-reports', projectId] - carries no money on its list rows: a CvrReport
 * is only period / status / currency / line_count, and the forecast/actual/
 * margin figures live in the per-report summary (fetched one report at a time),
 * so they cannot feed a cross-report chart from already-loaded rows. The panel
 * therefore charts the project's payment applications, the money-bearing flat
 * register the page also loads at the top level: each application carries gross,
 * retention and net-due amounts, a lifecycle status (draft -> submitted ->
 * certified -> paid) and a reporting period, so "value over time" and the status
 * split - the natural CVR centrepieces - are drawn from real money.
 *
 * When a project has no applications yet, the panel simply stays empty until
 * the register holds records. Status labels reuse the same
 * `cvr.payapp_status_*` i18n keys the applications table uses, so a chart slice
 * reads exactly like the status pill on the row it came from.
 *
 * Money crosses the wire as Decimal-as-string; it is only ever coerced to a
 * finite number for charting (Number(x) || 0), never used in wire arithmetic.
 * The reporting period is already a 'YYYY-MM' bucket, so it is used directly as
 * the time axis (no monthKey helper is needed).
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';

type Translate = ReturnType<typeof useTranslation>['t'];

/**
 * Minimal shape the builder needs from a payment application. The module's
 * `PaymentApplication` type structurally satisfies this (money fields stay
 * `number | string` so the raw record is assignable without a cast).
 */
interface PayappLite {
  application_number?: string | null;
  period?: string;
  status?: string;
  gross_value?: number | string;
  retention?: number | string;
  net_value?: number | string;
  currency?: string;
}

// Statuses that mean the application has been certified for payment (or already
// paid) - used for the two derived 0/1 flag measures.
const CERTIFIED_STATUSES = ['certified', 'paid'];

// Human labels for the application status enum, kept as the t() defaultValue so
// English reads well before the locale keys land.
const STATUS_LABELS: Record<string, string> = {
  draft: 'Draft',
  submitted: 'Submitted',
  certified: 'Certified',
  paid: 'Paid',
};

/** Fallback for an unknown code: "part_paid" -> "Part paid". */
function humanize(code: string): string {
  const spaced = code.replace(/_/g, ' ').trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : spaced;
}

/** Reuse the applications table's `cvr.payapp_status_*` keys so a chart slice
 *  reads exactly like the status pill on the row it came from. */
function statusLabel(code: string, t: Translate): string {
  return t(`cvr.payapp_status_${code}`, { defaultValue: STATUS_LABELS[code] ?? humanize(code) });
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  application: string;
  status: string;
  period: string;
  gross: number;
  retention: number;
  net: number;
  certified: number;
  paid: number;
}

function toRow(app: PayappLite, unnumbered: string, t: Translate): Row {
  const status = app.status ?? '';
  return {
    application: app.application_number?.trim() || unnumbered,
    status: statusLabel(status, t),
    period: app.period || '—',
    gross: Number(app.gross_value) || 0,
    retention: Number(app.retention) || 0,
    net: Number(app.net_value) || 0,
    certified: CERTIFIED_STATUSES.includes(status) ? 1 : 0,
    paid: status === 'paid' ? 1 : 0,
  };
}

export interface CvrInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildCvrInsights(
  applications: PayappLite[],
  currency: string,
  t: Translate,
): CvrInsights {
  const unnumbered = t('cvr.insights.unnumbered', { defaultValue: 'Unnumbered' });

  const rows: Row[] = [...applications]
    .sort((a, b) => (a.period ?? '').localeCompare(b.period ?? ''))
    .map((a) => toRow(a, unnumbered, t));

  const dataset: InsightDataset = {
    id: 'payapps',
    label: t('cvr.insights.ds_payapps', { defaultValue: 'Payment applications' }),
    currency: currency || '',
    fields: [
      { key: 'application', label: t('cvr.insights.f_application', { defaultValue: 'Application' }), kind: 'dimension' },
      { key: 'status', label: t('cvr.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'period', label: t('cvr.insights.f_period', { defaultValue: 'Period' }), kind: 'dimension' },
      { key: 'gross', label: t('cvr.insights.f_gross', { defaultValue: 'Gross applied' }), kind: 'measure', format: 'currency' },
      { key: 'retention', label: t('cvr.insights.f_retention', { defaultValue: 'Retention held' }), kind: 'measure', format: 'currency' },
      { key: 'net', label: t('cvr.insights.f_net', { defaultValue: 'Net due' }), kind: 'measure', format: 'currency' },
      { key: 'certified', label: t('cvr.insights.f_certified', { defaultValue: 'Certified' }), kind: 'measure', format: 'number' },
      { key: 'paid', label: t('cvr.insights.f_paid', { defaultValue: 'Paid' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'payapps', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-count', title: t('cvr.insights.k_count', { defaultValue: 'Applications' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-net', title: t('cvr.insights.k_net', { defaultValue: 'Net due' }), chart: 'kpi', measure: 'net', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-gross', title: t('cvr.insights.k_gross', { defaultValue: 'Gross applied' }), chart: 'kpi', measure: 'gross', agg: 'sum', color: 5 },
    { ...base, id: 'kpi-paid', title: t('cvr.insights.k_paid', { defaultValue: 'Paid' }), chart: 'kpi', measure: 'paid', agg: 'sum', color: 2 },
    { ...base, id: 'bar-net-by-status', title: t('cvr.insights.c_net_by_status', { defaultValue: 'Net due by status' }), chart: 'bar', dimension: 'status', measure: 'net', agg: 'sum', color: 1 },
    { ...base, id: 'donut-by-status', title: t('cvr.insights.c_by_status', { defaultValue: 'Applications by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'line-net-over-time', title: t('cvr.insights.c_net_over_time', { defaultValue: 'Net due over time' }), chart: 'line', dimension: 'period', measure: 'net', agg: 'sum', color: 5 },
    { ...base, id: 'area-gross-over-time', title: t('cvr.insights.c_gross_over_time', { defaultValue: 'Gross applied over time' }), chart: 'area', dimension: 'period', measure: 'gross', agg: 'sum', color: 3 },
  ];

  return { datasets: [dataset], builtins };
}
