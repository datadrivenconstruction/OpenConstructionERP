// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Markup register's contribution to the Module Insights panel: it turns the
 * markups the page already loaded into one dataset plus a set of built-in KPIs
 * and charts (markups by type, by status, assigned versus unassigned, and how
 * many are raised over time). When a document has no markups yet, the panel
 * simply stays empty until the register holds records.
 *
 * Value labels reuse the same `markups.type_*` / `markups.status_*` i18n keys
 * the markup list uses, so a slice in a chart reads exactly like the badge on
 * the row it came from. These are count insights: a markup carries no money
 * field, so every measure is a plain number - a count or a 0/1 flag - there is
 * no currency KPI. Its measurement_value is deliberately never summed either,
 * because those values mix units (metres, square metres and plain counts) and a
 * sum across them would be meaningless; the "Measurements" figure just counts
 * the markups that carry one.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';

type Translate = ReturnType<typeof useTranslation>['t'];

// Minimal shape this builder needs from a markup. The page hands it the full
// Markup[] (structurally a superset of this), so no mapping is needed at the
// call site.
interface MarkupLite {
  type: string;
  status: string;
  label: string | null;
  text: string | null;
  assignee_id: string | null;
  measurement_value: number | null;
  created_at: string;
}

// English fallbacks for the type badge; the real translation wins when present.
// Mirrors the markup list, which reads markups.type_<type> with the same
// fallbacks (some newer types have no dedicated key yet and fall back here).
const TYPE_LABELS: Record<string, string> = {
  cloud: 'Cloud',
  arrow: 'Arrow',
  text: 'Text',
  rectangle: 'Rectangle',
  highlight: 'Highlight',
  distance: 'Distance',
  area: 'Area',
  count: 'Count',
  stamp: 'Stamp',
  polygon: 'Polygon',
};

const STATUS_LABELS: Record<string, string> = {
  active: 'Active',
  resolved: 'Resolved',
  archived: 'Archived',
};

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '-';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function humanize(code: string): string {
  const s = code.replace(/_/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function typeLabel(code: string, t: Translate): string {
  return t(`markups.type_${code}`, { defaultValue: TYPE_LABELS[code] ?? humanize(code) });
}

function statusLabel(code: string, t: Translate): string {
  return t(`markups.status_${code}`, { defaultValue: STATUS_LABELS[code] ?? humanize(code) });
}

// Assignment derived from assignee_id alone, so it is viewer-independent (the
// raw assignee_id / author_id fields are user UUIDs this builder cannot resolve
// to a name). It says whether the markup has an owner picked up on it yet.
function assignmentLabel(r: MarkupLite, t: Translate): string {
  return r.assignee_id
    ? t('markups.insights.assigned', { defaultValue: 'Assigned' })
    : t('markups.unassigned', { defaultValue: 'Unassigned' });
}

// A readable title for the row: its own label, else its text, else the type.
function titleLabel(r: MarkupLite, t: Translate): string {
  const label = r.label?.trim();
  if (label) return label;
  const text = r.text?.trim();
  if (text) return text;
  return typeLabel(r.type, t);
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  title: string;
  type: string;
  status: string;
  assignment: string;
  month: string;
  open: number;
  resolved: number;
  assigned: number;
  measurement: number;
}

function toRow(r: MarkupLite, t: Translate): Row {
  return {
    title: titleLabel(r, t),
    type: typeLabel(r.type, t),
    status: statusLabel(r.status, t),
    assignment: assignmentLabel(r, t),
    month: monthKey(r.created_at),
    open: r.status === 'active' ? 1 : 0,
    resolved: r.status === 'resolved' ? 1 : 0,
    assigned: r.assignee_id ? 1 : 0,
    measurement: r.measurement_value != null ? 1 : 0,
  };
}

export interface MarkupsInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildMarkupsInsights(
  markups: MarkupLite[],
  currency: string,
  t: Translate,
): MarkupsInsights {
  const rows: Row[] = [...markups]
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    .map((r) => toRow(r, t));

  const dataset: InsightDataset = {
    id: 'markups',
    label: t('markups.insights.ds_markups', { defaultValue: 'Markups' }),
    currency: currency || '',
    fields: [
      { key: 'title', label: t('markups.insights.f_title', { defaultValue: 'Markup' }), kind: 'dimension' },
      { key: 'type', label: t('markups.insights.f_type', { defaultValue: 'Type' }), kind: 'dimension' },
      { key: 'status', label: t('markups.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'assignment', label: t('markups.insights.f_assignment', { defaultValue: 'Assignment' }), kind: 'dimension' },
      { key: 'month', label: t('markups.insights.f_month', { defaultValue: 'Month raised' }), kind: 'dimension' },
      { key: 'open', label: t('markups.insights.f_open', { defaultValue: 'Active' }), kind: 'measure', format: 'number' },
      { key: 'resolved', label: t('markups.insights.f_resolved', { defaultValue: 'Resolved' }), kind: 'measure', format: 'number' },
      { key: 'assigned', label: t('markups.insights.f_assigned', { defaultValue: 'Assigned' }), kind: 'measure', format: 'number' },
      { key: 'measurement', label: t('markups.insights.f_measurement', { defaultValue: 'Measurement' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'markups', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-markups', title: t('markups.insights.k_markups', { defaultValue: 'Markups' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-active', title: t('markups.insights.k_active', { defaultValue: 'Active' }), chart: 'kpi', measure: 'open', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-resolved', title: t('markups.insights.k_resolved', { defaultValue: 'Resolved' }), chart: 'kpi', measure: 'resolved', agg: 'sum', color: 3 },
    { ...base, id: 'kpi-measurements', title: t('markups.insights.k_measurements', { defaultValue: 'Measurements' }), chart: 'kpi', measure: 'measurement', agg: 'sum', color: 4 },
    { ...base, id: 'bar-by-type', title: t('markups.insights.c_by_type', { defaultValue: 'Markups by type' }), chart: 'bar', dimension: 'type', agg: 'count', color: 0 },
    { ...base, id: 'donut-by-status', title: t('markups.insights.c_by_status', { defaultValue: 'Markups by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-by-assignment', title: t('markups.insights.c_by_assignment', { defaultValue: 'Markups by assignment' }), chart: 'bar', dimension: 'assignment', agg: 'count', color: 5 },
    { ...base, id: 'area-over-time', title: t('markups.insights.c_over_time', { defaultValue: 'Markups raised over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 3 },
  ];

  return { datasets: [dataset], builtins };
}
