// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Equipment's contribution to the Module Insights panel: it turns the fleet
 * register the page already loaded into one dataset plus a set of built-in KPIs
 * and charts (units by type, status and ownership, fleet value, assets added
 * over time). When there is no equipment yet, the panel simply stays empty
 * until the module holds records.
 *
 * The equipment record carries a real money field (`purchase_value`) and a
 * currency, so the fleet-value measure formats as currency (rented / leased
 * units carry no owned value and read as zero). Status and ownership are
 * rendered raw in the register table, so unlike the money-free sibling modules
 * this file defines its own `equipment.insights.status_*` / `own_*` value keys.
 * There is no named site field on the record (only lat/lng), so ownership takes
 * the place a location dimension would otherwise fill.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';

type Translate = ReturnType<typeof useTranslation>['t'];

/**
 * Minimal shape the builder needs from an equipment row. The page's real
 * `Equipment` type structurally satisfies this (its status / ownership unions
 * are assignable to `string`, and money stays `number | string | null`) so the
 * raw record is assignable without a cast.
 */
interface EquipmentLite {
  name: string;
  type_code: string;
  status: string;
  ownership: string;
  purchase_value?: number | string | null;
  currency?: string;
  created_at: string;
}

const IN_USE_STATUSES = ['active'];
const MAINTENANCE_STATUSES = ['under_maintenance'];

/** Human-readable English fallbacks for the raw status tokens. */
const STATUS_LABELS: Record<string, string> = {
  active: 'Active',
  under_maintenance: 'Under maintenance',
  decommissioned: 'Decommissioned',
  reserved: 'Reserved',
};

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

function statusLabel(code: string, t: Translate): string {
  return t(`equipment.insights.status_${code}`, {
    defaultValue: STATUS_LABELS[code] ?? (code.charAt(0).toUpperCase() + code.slice(1)),
  });
}

function ownershipLabel(code: string, t: Translate): string {
  return t(`equipment.insights.own_${code}`, {
    defaultValue: code.charAt(0).toUpperCase() + code.slice(1),
  });
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  name: string;
  type: string;
  status: string;
  ownership: string;
  month: string;
  value: number;
  in_use: number;
  maintenance: number;
}

function toRow(e: EquipmentLite, uncategorised: string, t: Translate): Row {
  return {
    name: e.name ?? '',
    type: (e.type_code || '').trim() || uncategorised,
    status: statusLabel(e.status, t),
    ownership: ownershipLabel(e.ownership, t),
    month: monthKey(e.created_at),
    value: toNum(e.purchase_value),
    in_use: IN_USE_STATUSES.includes(e.status) ? 1 : 0,
    maintenance: MAINTENANCE_STATUSES.includes(e.status) ? 1 : 0,
  };
}

export interface EquipmentInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildEquipmentInsights(
  equipment: EquipmentLite[],
  currency: string,
  t: Translate,
): EquipmentInsights {
  const uncategorised = t('equipment.insights.uncategorised', { defaultValue: 'Uncategorised' });

  const rows: Row[] = [...equipment]
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    .map((e) => toRow(e, uncategorised, t));

  const dataset: InsightDataset = {
    id: 'equipment',
    label: t('equipment.insights.ds_equipment', { defaultValue: 'Fleet register' }),
    currency: currency || '',
    fields: [
      { key: 'name', label: t('equipment.insights.f_name', { defaultValue: 'Name' }), kind: 'dimension' },
      { key: 'type', label: t('equipment.insights.f_type', { defaultValue: 'Type' }), kind: 'dimension' },
      { key: 'status', label: t('equipment.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'ownership', label: t('equipment.insights.f_ownership', { defaultValue: 'Ownership' }), kind: 'dimension' },
      { key: 'month', label: t('equipment.insights.f_month', { defaultValue: 'Month added' }), kind: 'dimension' },
      { key: 'value', label: t('equipment.insights.f_value', { defaultValue: 'Asset value' }), kind: 'measure', format: 'currency' },
      { key: 'in_use', label: t('equipment.insights.f_in_use', { defaultValue: 'In use' }), kind: 'measure', format: 'number' },
      { key: 'maintenance', label: t('equipment.insights.f_maintenance', { defaultValue: 'In maintenance' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'equipment', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-units', title: t('equipment.insights.k_units', { defaultValue: 'Units' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-in-use', title: t('equipment.insights.k_in_use', { defaultValue: 'In use' }), chart: 'kpi', measure: 'in_use', agg: 'sum', color: 2 },
    { ...base, id: 'kpi-maintenance', title: t('equipment.insights.k_maintenance', { defaultValue: 'In maintenance' }), chart: 'kpi', measure: 'maintenance', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-value', title: t('equipment.insights.k_value', { defaultValue: 'Fleet value' }), chart: 'kpi', measure: 'value', agg: 'sum', color: 4 },
    { ...base, id: 'bar-by-type', title: t('equipment.insights.c_by_type', { defaultValue: 'Equipment by type' }), chart: 'bar', dimension: 'type', agg: 'count', color: 0 },
    { ...base, id: 'donut-by-status', title: t('equipment.insights.c_by_status', { defaultValue: 'Equipment by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-by-ownership', title: t('equipment.insights.c_by_ownership', { defaultValue: 'Equipment by ownership' }), chart: 'bar', dimension: 'ownership', agg: 'count', color: 1 },
    { ...base, id: 'area-over-time', title: t('equipment.insights.c_over_time', { defaultValue: 'Assets added over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
