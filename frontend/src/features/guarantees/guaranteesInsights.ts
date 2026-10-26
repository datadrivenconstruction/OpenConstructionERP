// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Guarantees register's contribution to the Module Insights panel: the
 * guarantees the page already loaded become one dataset with KPIs and charts
 * (by type, by bank, by status, expiry bands). The amount measure is formatted
 * as currency only when every guarantee shares one currency; with several
 * currencies a summed figure would mean nothing, so it is shown as a plain
 * number and the count measures carry the picture.
 */
import type { TFunction } from 'i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';
import type { Guarantee } from './api';
import { statusLabel, typeLabel } from './labels';

interface Row {
  [key: string]: string | number;
  reference: string;
  type: string;
  status: string;
  bank: string;
  band: string;
  amount: number;
  live: number;
  expiring: number;
}

export interface GuaranteesInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildGuaranteesInsights(guarantees: Guarantee[], t: TFunction): GuaranteesInsights {
  const currencies = new Set(guarantees.map((g) => g.currency));
  const currency = currencies.size === 1 ? [...currencies][0]! : '';
  const moneyFormat = currency ? 'currency' : 'number';

  const rows: Row[] = guarantees.map((g) => {
    const live = g.status === 'issued' || g.status === 'extended' || g.status === 'reduced' ? 1 : 0;
    return {
      reference: g.reference,
      type: typeLabel(t, g.guarantee_type),
      status: statusLabel(t, g.status),
      bank: g.issuer_bank?.trim() || t('guarantees.insights.no_bank', { defaultValue: 'No bank' }),
      band:
        g.alert_band === null
          ? t('guarantees.insights.band_none', { defaultValue: 'Not expiring soon' })
          : t('guarantees.insights.band_days', { defaultValue: 'Within {{days}} days', days: g.alert_band }),
      amount: live ? Number(g.amount) || 0 : 0,
      live,
      expiring: live && g.alert_band !== null ? 1 : 0,
    };
  });

  const dataset: InsightDataset = {
    id: 'guarantees',
    label: t('guarantees.insights.ds_guarantees', { defaultValue: 'Guarantee register' }),
    currency,
    fields: [
      { key: 'reference', label: t('guarantees.insights.f_reference', { defaultValue: 'Reference' }), kind: 'dimension' },
      { key: 'type', label: t('guarantees.insights.f_type', { defaultValue: 'Type' }), kind: 'dimension' },
      { key: 'status', label: t('guarantees.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'bank', label: t('guarantees.insights.f_bank', { defaultValue: 'Bank' }), kind: 'dimension' },
      { key: 'band', label: t('guarantees.insights.f_band', { defaultValue: 'Expiry band' }), kind: 'dimension' },
      { key: 'amount', label: t('guarantees.insights.f_amount', { defaultValue: 'Live amount' }), kind: 'measure', format: moneyFormat },
      { key: 'live', label: t('guarantees.insights.f_live', { defaultValue: 'Live' }), kind: 'measure', format: 'number' },
      { key: 'expiring', label: t('guarantees.insights.f_expiring', { defaultValue: 'Expiring soon' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'guarantees', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-guarantees', title: t('guarantees.insights.k_guarantees', { defaultValue: 'Guarantees' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-live', title: t('guarantees.insights.k_live', { defaultValue: 'Live' }), chart: 'kpi', measure: 'live', agg: 'sum', color: 4 },
    { ...base, id: 'kpi-expiring', title: t('guarantees.insights.k_expiring', { defaultValue: 'Expiring soon' }), chart: 'kpi', measure: 'expiring', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-amount', title: t('guarantees.insights.k_amount', { defaultValue: 'Live exposure' }), chart: 'kpi', measure: 'amount', agg: 'sum', color: 0 },
    { ...base, id: 'donut-by-status', title: t('guarantees.insights.c_by_status', { defaultValue: 'Guarantees by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-by-type', title: t('guarantees.insights.c_by_type', { defaultValue: 'Live amount by type' }), chart: 'bar', dimension: 'type', measure: 'amount', agg: 'sum', color: 0 },
    { ...base, id: 'bar-by-bank', title: t('guarantees.insights.c_by_bank', { defaultValue: 'Live amount by bank' }), chart: 'bar', dimension: 'bank', measure: 'amount', agg: 'sum', color: 5 },
    { ...base, id: 'bar-by-band', title: t('guarantees.insights.c_by_band', { defaultValue: 'Guarantees by expiry band' }), chart: 'bar', dimension: 'band', agg: 'count', color: 1 },
  ];

  return { datasets: [dataset], builtins };
}
