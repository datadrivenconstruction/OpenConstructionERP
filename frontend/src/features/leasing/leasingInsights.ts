// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Leasing's contribution to the Module Insights panel, built from the leases
 * the page already loaded: count, contracted rent per year, deposits held, the
 * status split and rent by unit. Money is converted only to chart it.
 */
import { useTranslation } from 'react-i18next';
import { toNum } from '@/shared/lib/money';
import type { InsightDataset, InsightDef } from '@/features/insights';
import type { Lease } from './api';
import { statusLabel } from './leasingLabels';

type Translate = ReturnType<typeof useTranslation>['t'];

const PER_YEAR: Record<string, number> = { monthly: 12, quarterly: 4, semiannual: 2, annual: 1 };

interface Row {
  [key: string]: string | number;
  code: string;
  unit: string;
  status: string;
  annual_rent: number;
  deposit: number;
}

export function buildLeasingInsights(
  leases: Lease[],
  t: Translate,
): { datasets: InsightDataset[]; builtins: InsightDef[] } {
  const currencies = new Set(leases.map((l) => l.currency));
  const currency = currencies.size === 1 ? [...currencies][0] ?? '' : '';
  const rows: Row[] = leases.map((l) => ({
    code: l.code,
    unit: l.unit_label || l.unit_ref,
    status: statusLabel(l.status, t),
    annual_rent: toNum(l.rent_amount) * (PER_YEAR[l.frequency] ?? 12),
    deposit: toNum(l.deposit),
  }));
  const dataset: InsightDataset = {
    id: 'leases',
    label: t('leasing.insights_ds', { defaultValue: 'Leases' }),
    currency,
    fields: [
      { key: 'code', label: t('leasing.col_code', { defaultValue: 'Lease' }), kind: 'dimension' },
      { key: 'unit', label: t('leasing.col_unit', { defaultValue: 'Unit' }), kind: 'dimension' },
      { key: 'status', label: t('leasing.col_status', { defaultValue: 'Status' }), kind: 'dimension' },
      {
        key: 'annual_rent',
        label: t('leasing.col_annual_rent', { defaultValue: 'Annual rent' }),
        kind: 'measure',
        format: currency ? 'currency' : 'number',
      },
      {
        key: 'deposit',
        label: t('leasing.col_deposit', { defaultValue: 'Deposit' }),
        kind: 'measure',
        format: currency ? 'currency' : 'number',
      },
    ],
    rows,
  };
  const base = { datasetId: 'leases', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-count', title: t('leasing.insights_count', { defaultValue: 'Leases' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-rent', title: t('leasing.col_annual_rent', { defaultValue: 'Annual rent' }), chart: 'kpi', measure: 'annual_rent', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-deposit', title: t('leasing.col_deposit', { defaultValue: 'Deposit' }), chart: 'kpi', measure: 'deposit', agg: 'sum', color: 2 },
    { ...base, id: 'donut-status', title: t('leasing.insights_by_status', { defaultValue: 'Leases by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-rent-unit', title: t('leasing.insights_rent_by_unit', { defaultValue: 'Annual rent by unit' }), chart: 'bar', dimension: 'unit', measure: 'annual_rent', agg: 'sum', color: 1 },
  ];
  return { datasets: [dataset], builtins };
}
