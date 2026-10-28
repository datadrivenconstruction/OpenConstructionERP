// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The drawing-sheet register's contribution to the Module Insights panel. It
 * turns the sheets the page already loaded into one dataset plus built-in KPIs
 * and charts (sheets by discipline, current versus superseded, by revision, and
 * how many were indexed over time). No extra request is made; when a project has
 * no sheets the panel simply stays empty.
 *
 * These are count insights. A sheet carries no money field of any kind, so every
 * measure is a plain number - a count or a 0/1 flag - and the dataset's currency
 * is deliberately empty. There is no currency KPI to be had here and inventing
 * one would invite arithmetic on a register that holds none.
 *
 * Two fields are deliberately NOT measures. `page_number` is an address inside a
 * PDF, so summing or averaging it produces a number with no meaning. And the
 * time series is bucketed on `created_at` (when the page was indexed) rather
 * than `revision_date`, which is nullable on most rows and would file the
 * majority of a real drawing set into a single "not set" bucket.
 *
 * The current/superseded labels reuse the same `sheets.is_current_*` keys the
 * table's own column uses, so a slice in a chart reads exactly like the cell it
 * came from.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';

type Translate = ReturnType<typeof useTranslation>['t'];

// Minimal shape this builder needs from a sheet. The page hands it the full
// SheetRow[] (structurally a superset of this), so no mapping is needed at the
// call site.
interface SheetLite {
  sheet_number: string | null;
  sheet_title: string | null;
  discipline: string | null;
  revision: string | null;
  scale: string | null;
  page_number: number;
  is_current: boolean;
  created_at: string;
}

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '-';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** Shared bucket for the nullable dimensions (discipline, revision, scale). */
function unset(t: Translate): string {
  return t('sheets.insights.unset', { defaultValue: 'Not set' });
}

// A readable row label: the sheet number, else its title, else the page it was
// extracted from - the same order the table's first column falls back through.
function sheetLabel(r: SheetLite, t: Translate): string {
  const number = r.sheet_number?.trim();
  if (number) return number;
  const title = r.sheet_title?.trim();
  if (title) return title;
  return t('sheets.insights.page_label', {
    defaultValue: 'Page {{page}}',
    page: r.page_number,
  });
}

function statusLabel(r: SheetLite, t: Translate): string {
  return r.is_current
    ? t('sheets.is_current_yes', { defaultValue: 'Current revision' })
    : t('sheets.is_current_no', { defaultValue: 'Superseded' });
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  sheet: string;
  discipline: string;
  revision: string;
  scale: string;
  status: string;
  month: string;
  current: number;
  superseded: number;
  revised: number;
}

function toRow(r: SheetLite, t: Translate): Row {
  return {
    sheet: sheetLabel(r, t),
    discipline: r.discipline?.trim() || unset(t),
    revision: r.revision?.trim() || unset(t),
    scale: r.scale?.trim() || unset(t),
    status: statusLabel(r, t),
    month: monthKey(r.created_at),
    current: r.is_current ? 1 : 0,
    superseded: r.is_current ? 0 : 1,
    revised: r.revision?.trim() ? 1 : 0,
  };
}

export interface SheetsInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildSheetsInsights(sheets: SheetLite[], t: Translate): SheetsInsights {
  const rows: Row[] = [...sheets]
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    .map((r) => toRow(r, t));

  const dataset: InsightDataset = {
    id: 'sheets',
    label: t('sheets.insights.ds_sheets', { defaultValue: 'Sheets' }),
    // A drawing sheet holds no money field, so there is no currency to declare.
    currency: '',
    fields: [
      { key: 'sheet', label: t('sheets.insights.f_sheet', { defaultValue: 'Sheet' }), kind: 'dimension' },
      { key: 'discipline', label: t('sheets.col_discipline', { defaultValue: 'Discipline' }), kind: 'dimension' },
      { key: 'revision', label: t('sheets.insights.f_revision', { defaultValue: 'Revision' }), kind: 'dimension' },
      { key: 'scale', label: t('sheets.col_scale', { defaultValue: 'Scale' }), kind: 'dimension' },
      { key: 'status', label: t('sheets.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'month', label: t('sheets.insights.f_month', { defaultValue: 'Month indexed' }), kind: 'dimension' },
      { key: 'current', label: t('sheets.insights.f_current', { defaultValue: 'Current' }), kind: 'measure', format: 'number' },
      { key: 'superseded', label: t('sheets.insights.f_superseded', { defaultValue: 'Superseded' }), kind: 'measure', format: 'number' },
      { key: 'revised', label: t('sheets.insights.f_revised', { defaultValue: 'Has a revision' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'sheets', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-sheets', title: t('sheets.insights.k_sheets', { defaultValue: 'Sheets' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-current', title: t('sheets.insights.k_current', { defaultValue: 'Current' }), chart: 'kpi', measure: 'current', agg: 'sum', color: 3 },
    { ...base, id: 'kpi-superseded', title: t('sheets.insights.k_superseded', { defaultValue: 'Superseded' }), chart: 'kpi', measure: 'superseded', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-revised', title: t('sheets.insights.k_revised', { defaultValue: 'With a revision' }), chart: 'kpi', measure: 'revised', agg: 'sum', color: 4 },
    { ...base, id: 'bar-by-discipline', title: t('sheets.insights.c_by_discipline', { defaultValue: 'Sheets by discipline' }), chart: 'bar', dimension: 'discipline', agg: 'count', color: 0 },
    { ...base, id: 'donut-by-status', title: t('sheets.insights.c_by_status', { defaultValue: 'Current versus superseded' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-by-revision', title: t('sheets.insights.c_by_revision', { defaultValue: 'Sheets by revision' }), chart: 'bar', dimension: 'revision', agg: 'count', color: 5 },
    { ...base, id: 'area-over-time', title: t('sheets.insights.c_over_time', { defaultValue: 'Sheets indexed over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 3 },
  ];

  return { datasets: [dataset], builtins };
}
