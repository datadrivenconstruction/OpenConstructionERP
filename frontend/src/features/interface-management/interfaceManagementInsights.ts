// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Interface register's contribution to the Module Insights panel: it turns the
 * interfaces the page already loaded into one dataset plus a set of built-in
 * KPIs and charts (interfaces by type, by status, by priority, and how many are
 * raised over time). When a project has no interfaces yet, the panel simply
 * stays empty until the module holds records.
 *
 * Value labels reuse the same `interface_management.status_*` / `type_*` /
 * `priority_*` i18n keys the register table uses (the module ships default maps
 * that humanize() reproduces exactly), so a slice in a chart reads exactly like
 * the badge on the row it came from. The overdue and settled flags reuse the
 * module's own `isInterfaceOverdue` / `isInterfaceSettled` rules, so a slice
 * counts an interface overdue on precisely the same basis as the red row. These
 * are count / status insights: an interface carries no money field, so every
 * measure is a plain number (a count or a day count) - there is no currency KPI.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';
import { isInterfaceOverdue, isInterfaceSettled } from './api';

type Translate = ReturnType<typeof useTranslation>['t'];

// Minimal shape this builder needs from an interface. The page hands it the full
// InterfaceRecord[] (structurally a superset of this), so no mapping is needed
// at the call site.
interface InterfaceLite {
  title: string;
  status: string;
  interface_type: string | null;
  priority: string | null;
  owner_party: string | null;
  need_by_date: string | null;
  created_at: string;
  updated_at: string;
}

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '-';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** Reasonable title-case fallback; the real translation wins when present. It
 *  also reproduces the module's STATUS_LABEL / TYPE_LABEL / PRIORITY_LABEL maps
 *  (all single words or underscore-separated), so slice labels equal the row
 *  badges even where en.ts has no explicit value key yet. */
function humanize(code: string): string {
  const s = code.replace(/_/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function statusLabel(code: string, t: Translate): string {
  return t(`interface_management.status_${code}`, { defaultValue: humanize(code) });
}

function typeLabel(code: string | null, t: Translate): string {
  if (!code) return t('interface_management.type_none', { defaultValue: 'No type' });
  return t(`interface_management.type_${code}`, { defaultValue: humanize(code) });
}

function priorityLabel(code: string | null, t: Translate): string {
  if (!code) return t('interface_management.priority_none', { defaultValue: 'No priority' });
  return t(`interface_management.priority_${code}`, { defaultValue: humanize(code) });
}

function ownerLabel(owner: string | null, t: Translate): string {
  const s = owner?.trim();
  return s ? s : t('interface_management.not_set', { defaultValue: 'Not set' });
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  title: string;
  status: string;
  type: string;
  priority: string;
  owner: string;
  month: string;
  open: number;
  overdue: number;
  agreed: number;
  age: number;
}

/** Whole days the interface has been (or was) open: created -> now for a live
 *  one, created -> last update for a settled (agreed / closed) one. Never
 *  negative. */
function daysOpen(r: InterfaceLite): number {
  const start = new Date(r.created_at).getTime();
  if (Number.isNaN(start)) return 0;
  const settled = isInterfaceSettled(r.status);
  const endRaw = settled ? new Date(r.updated_at).getTime() : Date.now();
  const end = Number.isNaN(endRaw) ? Date.now() : endRaw;
  return Math.max(0, Math.floor((end - start) / 86_400_000));
}

function toRow(r: InterfaceLite, today: string, t: Translate): Row {
  return {
    title: r.title ?? '',
    status: statusLabel(r.status, t),
    type: typeLabel(r.interface_type, t),
    priority: priorityLabel(r.priority, t),
    owner: ownerLabel(r.owner_party, t),
    month: monthKey(r.created_at),
    open: isInterfaceSettled(r.status) ? 0 : 1,
    overdue: isInterfaceOverdue(r, today) ? 1 : 0,
    agreed: r.status === 'agreed' ? 1 : 0,
    age: daysOpen(r),
  };
}

export interface InterfaceManagementInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildInterfaceManagementInsights(
  interfaces: InterfaceLite[],
  currency: string,
  t: Translate,
): InterfaceManagementInsights {
  const today = new Date().toISOString().slice(0, 10);

  const rows: Row[] = [...interfaces]
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    .map((r) => toRow(r, today, t));

  const dataset: InsightDataset = {
    id: 'interfaces',
    label: t('interface_management.insights.ds_interfaces', { defaultValue: 'Interface register' }),
    currency: currency || '',
    fields: [
      { key: 'title', label: t('interface_management.insights.f_title', { defaultValue: 'Interface' }), kind: 'dimension' },
      { key: 'type', label: t('interface_management.insights.f_type', { defaultValue: 'Type' }), kind: 'dimension' },
      { key: 'status', label: t('interface_management.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'priority', label: t('interface_management.insights.f_priority', { defaultValue: 'Priority' }), kind: 'dimension' },
      { key: 'owner', label: t('interface_management.insights.f_owner', { defaultValue: 'Owner party' }), kind: 'dimension' },
      { key: 'month', label: t('interface_management.insights.f_month', { defaultValue: 'Month raised' }), kind: 'dimension' },
      { key: 'open', label: t('interface_management.insights.f_open', { defaultValue: 'Open' }), kind: 'measure', format: 'number' },
      { key: 'overdue', label: t('interface_management.insights.f_overdue', { defaultValue: 'Overdue' }), kind: 'measure', format: 'number' },
      { key: 'agreed', label: t('interface_management.insights.f_agreed', { defaultValue: 'Agreed' }), kind: 'measure', format: 'number' },
      { key: 'age', label: t('interface_management.insights.f_age', { defaultValue: 'Days open' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'interfaces', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-interfaces', title: t('interface_management.insights.k_interfaces', { defaultValue: 'Interfaces' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-open', title: t('interface_management.insights.k_open', { defaultValue: 'Open' }), chart: 'kpi', measure: 'open', agg: 'sum', color: 0 },
    { ...base, id: 'kpi-overdue', title: t('interface_management.insights.k_overdue', { defaultValue: 'Overdue' }), chart: 'kpi', measure: 'overdue', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-avg-age', title: t('interface_management.insights.k_avg_age', { defaultValue: 'Avg days open' }), chart: 'kpi', measure: 'age', agg: 'avg', color: 4 },
    { ...base, id: 'bar-by-type', title: t('interface_management.insights.c_by_type', { defaultValue: 'Interfaces by type' }), chart: 'bar', dimension: 'type', agg: 'count', color: 0 },
    { ...base, id: 'donut-by-status', title: t('interface_management.insights.c_by_status', { defaultValue: 'Interfaces by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-by-priority', title: t('interface_management.insights.c_by_priority', { defaultValue: 'Interfaces by priority' }), chart: 'bar', dimension: 'priority', agg: 'count', color: 1 },
    { ...base, id: 'area-over-time', title: t('interface_management.insights.c_over_time', { defaultValue: 'Interfaces raised over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
