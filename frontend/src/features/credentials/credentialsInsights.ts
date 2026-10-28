// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The credentials register's contribution to the Module Insights panel.
 *
 * The register table answers "what does this holder hold". It does not answer
 * the two questions that decide whether a renewal is a diary note or a
 * scramble: where the lapses are concentrated, and how far past its date the
 * worst one already is. So the panel puts expiry against the holder, the
 * issuing authority and the credential type.
 *
 * Rows are the credentials the page already loaded - no extra request. A
 * credential carries no money, so the dataset declares no currency and no
 * measure is currency-formatted; a money tile here would invite a total that
 * does not exist.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';
import type { Credential } from './api';
import { holderKindLabel } from './labels';

type Translate = ReturnType<typeof useTranslation>['t'];

/** Resolves a vocabulary code to the words the table shows for it. */
export type Labeller = (code: string) => string;

/** Sortable YYYY-MM key so a time series stays chronological. */
function monthKey(iso: string | null, perpetual: string): string {
  if (!iso) return perpetual;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return perpetual;
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  holder: string;
  holder_kind: string;
  credential_type: string;
  discipline: string;
  authority: string;
  jurisdiction: string;
  status: string;
  expiry_month: string;
  expired: number;
  expiring: number;
  unverified: number;
  perpetual: number;
  days_lapsed: number;
}

export interface CredentialsInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

/**
 * Build the register dataset and its built-in charts.
 *
 * The two labellers are the page's own, so a slice reads with exactly the words
 * of the table column beside it rather than a second copy of the vocabulary
 * that would drift from the server's whitelist.
 */
export function buildCredentialsInsights(
  items: Credential[],
  t: Translate,
  typeLabel: Labeller,
  statusLabel: Labeller,
): CredentialsInsights {
  const none = t('credentials.insights.unset', { defaultValue: 'Not recorded' });
  const perpetual = t('credentials.insights.perpetual', { defaultValue: 'No expiry' });

  const rows: Row[] = items.map((c) => ({
    holder: c.holder_name.trim() || none,
    holder_kind: holderKindLabel(c.holder_kind, t),
    credential_type: typeLabel(c.credential_type),
    discipline: c.discipline?.trim() || none,
    authority: c.authority?.trim() || none,
    jurisdiction: c.jurisdiction?.trim() || none,
    status: statusLabel(c.status),
    expiry_month: monthKey(c.valid_until, perpetual),
    expired: c.status === 'expired' ? 1 : 0,
    expiring: c.status === 'expiring_soon' ? 1 : 0,
    unverified: c.verified_at ? 0 : 1,
    perpetual: c.valid_until === null ? 1 : 0,
    // Only a credential already past its date carries a lapse. Something due
    // next month has a positive days_until_expiry, and folding that in would
    // net off against real lapses and make the register look healthier than
    // it is.
    days_lapsed: c.days_until_expiry !== null && c.days_until_expiry < 0 ? -c.days_until_expiry : 0,
  }));

  const dataset: InsightDataset = {
    id: 'credentials',
    label: t('credentials.insights.ds_register', { defaultValue: 'Credentials register' }),
    currency: '',
    fields: [
      { key: 'holder', label: t('credentials.insights.f_holder', { defaultValue: 'Holder' }), kind: 'dimension' },
      { key: 'holder_kind', label: t('credentials.insights.f_holder_kind', { defaultValue: 'Held by' }), kind: 'dimension' },
      { key: 'credential_type', label: t('credentials.insights.f_type', { defaultValue: 'Credential type' }), kind: 'dimension' },
      { key: 'discipline', label: t('credentials.insights.f_discipline', { defaultValue: 'Discipline' }), kind: 'dimension' },
      { key: 'authority', label: t('credentials.insights.f_authority', { defaultValue: 'Issuing authority' }), kind: 'dimension' },
      { key: 'jurisdiction', label: t('credentials.insights.f_jurisdiction', { defaultValue: 'Jurisdiction' }), kind: 'dimension' },
      { key: 'status', label: t('credentials.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'expiry_month', label: t('credentials.insights.f_expiry_month', { defaultValue: 'Month of expiry' }), kind: 'dimension' },
      { key: 'expired', label: t('credentials.insights.f_expired', { defaultValue: 'Expired' }), kind: 'measure', format: 'number' },
      { key: 'expiring', label: t('credentials.insights.f_expiring', { defaultValue: 'Expiring soon' }), kind: 'measure', format: 'number' },
      { key: 'unverified', label: t('credentials.insights.f_unverified', { defaultValue: 'Unverified' }), kind: 'measure', format: 'number' },
      { key: 'perpetual', label: t('credentials.insights.f_perpetual', { defaultValue: 'No expiry date' }), kind: 'measure', format: 'number' },
      { key: 'days_lapsed', label: t('credentials.insights.f_days_lapsed', { defaultValue: 'Days lapsed' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'credentials', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-held', title: t('credentials.insights.k_held', { defaultValue: 'Credentials on register' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-expired', title: t('credentials.insights.k_expired', { defaultValue: 'Expired' }), chart: 'kpi', measure: 'expired', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-expiring', title: t('credentials.insights.k_expiring', { defaultValue: 'Expiring soon' }), chart: 'kpi', measure: 'expiring', agg: 'sum', color: 4 },
    { ...base, id: 'kpi-unverified', title: t('credentials.insights.k_unverified', { defaultValue: 'Never verified' }), chart: 'kpi', measure: 'unverified', agg: 'sum', color: 5 },
    { ...base, id: 'kpi-worst-lapse', title: t('credentials.insights.k_worst_lapse', { defaultValue: 'Longest lapse (days)' }), chart: 'kpi', measure: 'days_lapsed', agg: 'max', color: 1 },
    { ...base, id: 'bar-by-type', title: t('credentials.insights.c_by_type', { defaultValue: 'Credentials by type' }), chart: 'bar', dimension: 'credential_type', agg: 'count', color: 0 },
    { ...base, id: 'bar-lapsed-by-holder', title: t('credentials.insights.c_lapsed_by_holder', { defaultValue: 'Expired by holder' }), chart: 'bar', dimension: 'holder', measure: 'expired', agg: 'sum', color: 1 },
    { ...base, id: 'donut-by-status', title: t('credentials.insights.c_by_status', { defaultValue: 'Register by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-unverified-by-authority', title: t('credentials.insights.c_unverified_by_authority', { defaultValue: 'Unverified by issuing authority' }), chart: 'bar', dimension: 'authority', measure: 'unverified', agg: 'sum', color: 5 },
    { ...base, id: 'line-expiry-month', title: t('credentials.insights.c_expiry_month', { defaultValue: 'Expiries by month' }), chart: 'line', dimension: 'expiry_month', agg: 'count', color: 0 },
  ];

  return { datasets: [dataset], builtins };
}
