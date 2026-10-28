// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Contracts' contribution to the Module Insights panel: it turns the contract
 * register the page already loaded into one dataset plus a set of built-in KPIs
 * and charts (contract value by type, contracts by status and counterparty,
 * register value over time). When a project has no contracts yet, the panel
 * simply stays empty until the register holds records.
 *
 * Labels reuse the same `contracts.type_*` / `contracts.status_*` /
 * `contracts.cp_*` i18n keys the register table uses, so a slice in a chart
 * reads exactly like the chip on the row it came from. The contract value is a
 * real money field (`total_value`), so its measures format as currency.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';

// English fallbacks for the computed `contracts.type_*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const CONTRACTS_TYPE_LABELS: Record<string, string> = {
  lump_sum: 'Lump sum', gmp: 'GMP', cost_plus: 'Cost plus', tm: 'T&M', unit_price: 'Unit price',
  design_build: 'Design and build', combination: 'Combination', remeasurement: 'Remeasurement'
};


type Translate = ReturnType<typeof useTranslation>['t'];

/**
 * Minimal shape the builder needs from a contract row. The page's real
 * `ContractItem` type structurally satisfies this (its string-literal unions are
 * assignable to `string`, and money stays `number | string`) so the raw record
 * is assignable without a cast.
 */
interface ContractLite {
  title: string;
  contract_type: string;
  status: string;
  counterparty_type: string;
  total_value: number | string;
  currency?: string;
  created_at: string;
}

const ACTIVE_STATUSES = ['active'];

/** Coerce a money cell (Decimal-as-string on the wire) to a finite number. */
function toNum(v: number | string | null | undefined): number {
  if (v === null || v === undefined) return 0;
  const n = typeof v === 'string' ? Number(v) : v;
  return Number.isFinite(n) ? n : 0;
}

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** Reuse the register's own type chip label so a slice reads like the row. */
function typeLabel(code: string, t: Translate): string {
  return t(`contracts.type_${code}`, {
    defaultValue: CONTRACTS_TYPE_LABELS[code] ?? (code === 'tm' ? 'T&M' : code.replace(/_/g, ' ')),
  });
}

function statusLabel(code: string, t: Translate): string {
  return t(`contracts.status_${code}`, {
    defaultValue: code.charAt(0).toUpperCase() + code.slice(1),
  });
}

/** Client vs subcontractor - reuse the counterparty words the table shows. */
function partyLabel(code: string, t: Translate): string {
  if (code === 'subcontractor') {
    return t('contracts.cp_subcontractor', { defaultValue: 'Subcontractor' });
  }
  if (code === 'client') {
    return t('contracts.cp_client', { defaultValue: 'Client' });
  }
  return code ? code.charAt(0).toUpperCase() + code.slice(1) : '';
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  title: string;
  type: string;
  status: string;
  party: string;
  month: string;
  value: number;
  active: number;
}

function toRow(c: ContractLite, t: Translate): Row {
  return {
    title: c.title ?? '',
    type: typeLabel(c.contract_type, t),
    status: statusLabel(c.status, t),
    party: partyLabel(c.counterparty_type, t),
    month: monthKey(c.created_at),
    value: toNum(c.total_value),
    active: ACTIVE_STATUSES.includes(c.status) ? 1 : 0,
  };
}

export interface ContractsInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildContractsInsights(
  contracts: ContractLite[],
  currency: string,
  t: Translate,
): ContractsInsights {
  const rows: Row[] = [...contracts]
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    .map((c) => toRow(c, t));

  const dataset: InsightDataset = {
    id: 'contracts',
    label: t('contracts.insights.ds_contracts', { defaultValue: 'Contract register' }),
    currency: currency || '',
    fields: [
      { key: 'title', label: t('contracts.insights.f_title', { defaultValue: 'Contract' }), kind: 'dimension' },
      { key: 'type', label: t('contracts.insights.f_type', { defaultValue: 'Type' }), kind: 'dimension' },
      { key: 'status', label: t('contracts.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'party', label: t('contracts.insights.f_party', { defaultValue: 'Counterparty' }), kind: 'dimension' },
      { key: 'month', label: t('contracts.insights.f_month', { defaultValue: 'Month added' }), kind: 'dimension' },
      { key: 'value', label: t('contracts.insights.f_value', { defaultValue: 'Contract value' }), kind: 'measure', format: 'currency' },
      { key: 'active', label: t('contracts.insights.f_active', { defaultValue: 'Active' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'contracts', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-contracts', title: t('contracts.insights.k_contracts', { defaultValue: 'Contracts' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-value', title: t('contracts.insights.k_value', { defaultValue: 'Total contract value' }), chart: 'kpi', measure: 'value', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-active', title: t('contracts.insights.k_active', { defaultValue: 'Active' }), chart: 'kpi', measure: 'active', agg: 'sum', color: 2 },
    { ...base, id: 'kpi-avg-value', title: t('contracts.insights.k_avgvalue', { defaultValue: 'Avg contract value' }), chart: 'kpi', measure: 'value', agg: 'avg', color: 4 },
    { ...base, id: 'bar-value-by-type', title: t('contracts.insights.c_value_by_type', { defaultValue: 'Contract value by type' }), chart: 'bar', dimension: 'type', measure: 'value', agg: 'sum', color: 1 },
    { ...base, id: 'donut-by-status', title: t('contracts.insights.c_by_status', { defaultValue: 'Contracts by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-by-party', title: t('contracts.insights.c_by_party', { defaultValue: 'Contracts by counterparty' }), chart: 'bar', dimension: 'party', agg: 'count', color: 0 },
    { ...base, id: 'area-value-over-time', title: t('contracts.insights.c_over_time', { defaultValue: 'Contract value over time' }), chart: 'area', dimension: 'month', measure: 'value', agg: 'sum', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
