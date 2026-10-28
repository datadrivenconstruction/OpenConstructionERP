// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Accommodation register's contribution to the Module Insights panel: it turns
 * the properties the page already loaded into one dataset plus a set of built-in
 * KPIs and charts (capacity by type, properties by type, how many are pinned on
 * the map, and how the register grows over time). The panel stays empty until
 * the register holds accommodation records.
 *
 * Value labels reuse the same `accommodation.kind.*` i18n keys the register uses,
 * so a slice in a chart reads exactly like the badge on the row it came from.
 * These are count / capacity insights: an accommodation record carries no money
 * field (rates live on its rooms and charges, not on the list row), so every
 * measure is a plain number - a head count or a 0/1 flag - there is no currency
 * KPI.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';

type Translate = ReturnType<typeof useTranslation>['t'];

// Minimal shape this builder needs from an accommodation. The page hands it the
// full Accommodation[] (structurally a superset of this), so no mapping is
// needed at the call site.
interface AccommodationLite {
  name: string;
  kind: string;
  capacity_total: number;
  // Coordinates arrive as Decimal-encoded strings (or null), matching the
  // Accommodation API type; this builder only cares whether both are present.
  geo_lat: string | null;
  geo_lon: string | null;
  created_at: string;
}

// English fallbacks for the kind badge; the real translation wins when present.
const KIND_LABELS: Record<string, string> = {
  worker_camp: 'Worker camp',
  rental: 'Rental',
  hotel: 'Hotel',
};

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '-';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function kindLabel(code: string, t: Translate): string {
  const fallback = KIND_LABELS[code] ?? code.charAt(0).toUpperCase() + code.slice(1);
  return t(`accommodation.kind.${code}`, { defaultValue: fallback });
}

// A property is "on the map" once it has both coordinates. This is a real,
// viewer-independent property of the row and makes a useful coverage slice
// (how much of the register is actually located).
function isMapped(r: AccommodationLite): boolean {
  return !!r.geo_lat && !!r.geo_lon;
}

function locatedLabel(r: AccommodationLite, t: Translate): string {
  return isMapped(r)
    ? t('accommodation.insights.geo_mapped', { defaultValue: 'On map' })
    : t('accommodation.insights.geo_none', { defaultValue: 'No location' });
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  name: string;
  kind: string;
  located: string;
  month: string;
  capacity: number;
  mapped: number;
  camp: number;
}

function toRow(r: AccommodationLite, t: Translate): Row {
  return {
    name: r.name ?? '',
    kind: kindLabel(r.kind, t),
    located: locatedLabel(r, t),
    month: monthKey(r.created_at),
    capacity: r.capacity_total ?? 0,
    mapped: isMapped(r) ? 1 : 0,
    camp: r.kind === 'worker_camp' ? 1 : 0,
  };
}

export interface AccommodationInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildAccommodationInsights(
  accommodations: AccommodationLite[],
  currency: string,
  t: Translate,
): AccommodationInsights {
  const rows: Row[] = [...accommodations]
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    .map((r) => toRow(r, t));

  const dataset: InsightDataset = {
    id: 'accommodation',
    label: t('accommodation.insights.ds_accommodation', { defaultValue: 'Accommodation register' }),
    currency: currency || '',
    fields: [
      { key: 'name', label: t('accommodation.insights.f_name', { defaultValue: 'Property' }), kind: 'dimension' },
      { key: 'kind', label: t('accommodation.insights.f_kind', { defaultValue: 'Type' }), kind: 'dimension' },
      { key: 'located', label: t('accommodation.insights.f_located', { defaultValue: 'Map coverage' }), kind: 'dimension' },
      { key: 'month', label: t('accommodation.insights.f_month', { defaultValue: 'Month added' }), kind: 'dimension' },
      { key: 'capacity', label: t('accommodation.insights.f_capacity', { defaultValue: 'Capacity (beds)' }), kind: 'measure', format: 'number' },
      { key: 'mapped', label: t('accommodation.insights.f_mapped', { defaultValue: 'On map' }), kind: 'measure', format: 'number' },
      { key: 'camp', label: t('accommodation.insights.f_camp', { defaultValue: 'Worker camp' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'accommodation', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-properties', title: t('accommodation.insights.k_properties', { defaultValue: 'Properties' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-capacity', title: t('accommodation.insights.k_capacity', { defaultValue: 'Total capacity' }), chart: 'kpi', measure: 'capacity', agg: 'sum', color: 4 },
    { ...base, id: 'kpi-avg-capacity', title: t('accommodation.insights.k_avg_capacity', { defaultValue: 'Avg capacity' }), chart: 'kpi', measure: 'capacity', agg: 'avg', color: 3 },
    { ...base, id: 'kpi-camps', title: t('accommodation.insights.k_camps', { defaultValue: 'Worker camps' }), chart: 'kpi', measure: 'camp', agg: 'sum', color: 1 },
    { ...base, id: 'bar-capacity-by-kind', title: t('accommodation.insights.c_capacity_by_kind', { defaultValue: 'Capacity by type' }), chart: 'bar', dimension: 'kind', measure: 'capacity', agg: 'sum', color: 4 },
    { ...base, id: 'donut-by-kind', title: t('accommodation.insights.c_by_kind', { defaultValue: 'Properties by type' }), chart: 'donut', dimension: 'kind', agg: 'count', color: 0 },
    { ...base, id: 'bar-by-located', title: t('accommodation.insights.c_by_located', { defaultValue: 'Properties by map coverage' }), chart: 'bar', dimension: 'located', agg: 'count', color: 5 },
    { ...base, id: 'area-over-time', title: t('accommodation.insights.c_over_time', { defaultValue: 'Properties added over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 3 },
  ];

  return { datasets: [dataset], builtins };
}
