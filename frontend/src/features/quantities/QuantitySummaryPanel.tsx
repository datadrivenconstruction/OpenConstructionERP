// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * QuantitySummaryPanel - a read-only rollup of the measured quantities that
 * already exist for the active project, aggregated entirely on the client from
 * two existing endpoints:
 *   - PDF takeoff measurements (`/v1/takeoff/measurements/`)
 *   - BOQ position quantities  (`/v1/boq/boqs/` + `/v1/boq/boqs/{id}`)
 *
 * It turns the Quantity Takeoff hub from a launcher into a surface that shows
 * real numbers: how much has been measured, in which units, per trade / type /
 * source, with a Decimal-safe total and a one-click CSV export. Nothing is
 * written back; this is a reporting view over what the takeoff and estimate
 * modules already captured.
 */

import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Ruler,
  Box,
  Sparkles,
  Layers3,
  ArrowRight,
  Download,
  Filter,
  Table2,
  FileText,
  X,
  RotateCcw,
} from 'lucide-react';
import {
  EmptyState,
  ErrorState,
  Skeleton,
  Button,
  InfoHint,
  QuantityDisplay,
} from '@/shared/ui';
import { takeoffApi } from '../takeoff/api';
import { boqApi } from '../boq/api';
import {
  measurementsToRecords,
  boqsToRecords,
  aggregateRecords,
  totalsByUnit,
  groupRows,
  distinctValues,
  buildQuantitiesCsv,
  downloadCsv,
  quantitiesCsvName,
  NO_UNIT,
  type BoqPositions,
  type QuantityRecord,
  type QuantitySource,
  type RollupDimension,
  type RollupRow,
} from './quantitiesRollup';

export interface QuantitySummaryPanelProps {
  /** Active project id from the global project context (null when none chosen). */
  projectId: string | null;
  /** Active project name, used for the CSV filename. */
  projectName: string;
  /** Controlled document filter (set by the Recent Documents "View quantities" action). */
  documentId?: string | null;
  /** Notifies the parent when the in-panel document filter changes. */
  onDocumentChange?: (id: string | null) => void;
}

/** Human fallback for a measurement kind when no explicit i18n key resolves. */
function prettyKind(kind: string): string {
  if (kind === 'boq_line') return 'BOQ line';
  return kind.charAt(0).toUpperCase() + kind.slice(1);
}

/* ── Source badge ────────────────────────────────────────────────────── */

function SourceBadge({ source, label }: { source: QuantitySource; label: string }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded px-1.5 py-0.5 text-2xs font-medium',
        source === 'takeoff'
          ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300'
          : 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300',
      )}
    >
      {label}
    </span>
  );
}

/* ── Flow strip (what this page is + how it connects) ────────────────── */

function FlowStrip() {
  const { t } = useTranslation();
  const node = (icon: React.ReactNode, label: string) => (
    <span className="inline-flex items-center gap-1.5 rounded-lg bg-surface-secondary px-2.5 py-1 text-xs font-medium text-content-secondary">
      {icon}
      {label}
    </span>
  );
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="inline-flex items-center gap-1.5">
        {node(<Ruler size={13} className="text-blue-500" />, t('quantities.flow_takeoff', { defaultValue: 'Takeoff' }))}
        {node(<Box size={13} className="text-emerald-500" />, t('quantities.flow_cad', { defaultValue: 'CAD / BIM' }))}
        {node(<Sparkles size={13} className="text-violet-500" />, t('quantities.flow_ai', { defaultValue: 'AI' }))}
      </span>
      <ArrowRight size={14} className="text-content-quaternary" />
      {node(<Layers3 size={13} className="text-oe-blue" />, t('quantities.flow_measured', { defaultValue: 'Measured quantities' }))}
      <ArrowRight size={14} className="text-content-quaternary" />
      {node(<Table2 size={13} className="text-content-tertiary" />, t('quantities.flow_boq', { defaultValue: 'BOQ / estimate' }))}
    </div>
  );
}

/* ── Filter select ───────────────────────────────────────────────────── */

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: Array<{ value: string; label: string }>;
}) {
  return (
    <label className="flex items-center gap-1.5 text-xs">
      <span className="text-content-tertiary">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-border-light bg-surface-primary px-2 py-1 text-xs text-content-primary focus:border-oe-blue focus:outline-none"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/* ── Rollup rows table ───────────────────────────────────────────────── */

function RollupTableRow({
  row,
  sourceLabel,
}: {
  row: RollupRow;
  sourceLabel: (s: QuantitySource) => string;
}) {
  const { t } = useTranslation();
  const displayUnit = row.unit === NO_UNIT ? '' : row.unit;
  return (
    <tr className="border-b border-border-light last:border-0 hover:bg-surface-secondary/50">
      <td className="py-2 pr-4">
        <span className="font-mono text-xs text-content-secondary">
          {row.unit === NO_UNIT ? t('quantities.no_unit', { defaultValue: 'No unit' }) : row.unit}
        </span>
      </td>
      <td className="py-2 pr-4 text-right tabular-nums text-content-tertiary">{row.count}</td>
      <td className="py-2 pr-4 text-right tabular-nums font-medium text-content-primary">
        <QuantityDisplay value={row.total} unit={displayUnit} precision={2} />
      </td>
      <td className="py-2">
        <div className="flex flex-wrap gap-1">
          {row.sources.map((s) => (
            <SourceBadge key={s} source={s} label={sourceLabel(s)} />
          ))}
        </div>
      </td>
    </tr>
  );
}

/* ── Panel ───────────────────────────────────────────────────────────── */

export function QuantitySummaryPanel({
  projectId,
  projectName,
  documentId,
  onDocumentChange,
}: QuantitySummaryPanelProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [dimension, setDimension] = useState<RollupDimension>('unit');
  const [sourceFilter, setSourceFilter] = useState<'' | QuantitySource>('');
  const [unitFilter, setUnitFilter] = useState('');
  const [tradeFilter, setTradeFilter] = useState('');
  const [localDoc, setLocalDoc] = useState<string | null>(null);

  const docFilter = documentId !== undefined ? documentId : localDoc;
  const setDocFilter = useCallback(
    (id: string | null) => {
      if (onDocumentChange) onDocumentChange(id);
      else setLocalDoc(id);
    },
    [onDocumentChange],
  );

  /* ── Queries ──────────────────────────────────────────────────────── */

  const measureQuery = useQuery({
    queryKey: ['quantities', 'measurements', projectId],
    queryFn: () => takeoffApi.list(projectId as string),
    enabled: !!projectId,
    staleTime: 30_000,
  });

  const boqQuery = useQuery({
    queryKey: ['quantities', 'boq-rollup', projectId],
    queryFn: async (): Promise<BoqPositions[]> => {
      const boqs = await boqApi.list(projectId as string);
      return Promise.all(
        boqs.map((b) =>
          boqApi.get(b.id).then(
            (full): BoqPositions => ({ name: b.name, positions: full.positions ?? [] }),
            (): BoqPositions => ({ name: b.name, positions: [] }),
          ),
        ),
      );
    },
    enabled: !!projectId,
    staleTime: 30_000,
  });

  const docsQuery = useQuery({
    queryKey: ['takeoff-documents', projectId ?? 'all'],
    queryFn: () => takeoffApi.listDocuments(projectId ?? undefined),
    enabled: !!projectId,
    staleTime: 30_000,
  });

  /* ── Derived data ─────────────────────────────────────────────────── */

  const records: QuantityRecord[] = useMemo(() => {
    const tk = measureQuery.data ? measurementsToRecords(measureQuery.data) : [];
    const bq = boqQuery.data ? boqsToRecords(boqQuery.data) : [];
    return [...tk, ...bq];
  }, [measureQuery.data, boqQuery.data]);

  const unitOptions = useMemo(() => distinctValues(records, (r) => r.unit || NO_UNIT), [records]);
  const tradeOptions = useMemo(() => distinctValues(records, (r) => r.trade), [records]);

  const docIdsWithData = useMemo(() => {
    const s = new Set<string>();
    for (const r of records) if (r.source === 'takeoff' && r.documentId) s.add(r.documentId);
    return s;
  }, [records]);

  const docOptions = useMemo(
    () => (docsQuery.data ?? []).filter((d) => docIdsWithData.has(d.id)),
    [docsQuery.data, docIdsWithData],
  );

  const filtered = useMemo(
    () =>
      records.filter((r) => {
        if (sourceFilter && r.source !== sourceFilter) return false;
        if (unitFilter && (r.unit || NO_UNIT) !== unitFilter) return false;
        if (tradeFilter && r.trade !== tradeFilter) return false;
        if (docFilter) {
          if (r.source !== 'takeoff') return false;
          if ((r.documentId ?? '') !== docFilter) return false;
        }
        return true;
      }),
    [records, sourceFilter, unitFilter, tradeFilter, docFilter],
  );

  const rows = useMemo(() => aggregateRecords(filtered, dimension), [filtered, dimension]);
  const unitTotals = useMemo(() => totalsByUnit(filtered), [filtered]);
  const grouped = useMemo(() => groupRows(rows), [rows]);

  /* ── Labels ───────────────────────────────────────────────────────── */

  const sourceLabel = useCallback(
    (s: QuantitySource) =>
      s === 'takeoff'
        ? t('quantities.source_takeoff', { defaultValue: 'Takeoff' })
        : t('quantities.source_boq', { defaultValue: 'BOQ' }),
    [t],
  );

  const kindLabel = useCallback(
    (k: string) => t(`quantities.kind_${k}`, { defaultValue: prettyKind(k) }),
    [t],
  );

  const groupLabelFor = useCallback(
    (group: string): string => {
      if (dimension === 'source') return sourceLabel(group as QuantitySource);
      if (dimension === 'kind') return kindLabel(group);
      if (dimension === 'unit' && group === NO_UNIT)
        return t('quantities.no_unit', { defaultValue: 'No unit' });
      return group;
    },
    [dimension, sourceLabel, kindLabel, t],
  );

  const groupColumnHeader = useMemo(() => {
    switch (dimension) {
      case 'trade':
        return t('quantities.col_trade', { defaultValue: 'Trade / group' });
      case 'kind':
        return t('quantities.col_type', { defaultValue: 'Type' });
      case 'source':
        return t('quantities.col_source', { defaultValue: 'Source' });
      default:
        return t('quantities.col_unit', { defaultValue: 'Unit' });
    }
  }, [dimension, t]);

  /* ── Filters + export ─────────────────────────────────────────────── */

  const hasActiveFilters = Boolean(sourceFilter || unitFilter || tradeFilter || docFilter);

  const resetFilters = useCallback(() => {
    setSourceFilter('');
    setUnitFilter('');
    setTradeFilter('');
    setDocFilter(null);
  }, [setDocFilter]);

  const handleExport = useCallback(() => {
    if (rows.length === 0) return;
    const csvRows: RollupRow[] = rows.map((r) => ({ ...r, group: groupLabelFor(r.group) }));
    const csv = buildQuantitiesCsv(csvRows, {
      group: groupColumnHeader,
      unit: t('quantities.col_unit', { defaultValue: 'Unit' }),
      count: t('quantities.col_measurements', { defaultValue: 'Measurements' }),
      total: t('quantities.col_total', { defaultValue: 'Total quantity' }),
      sources: t('quantities.col_sources', { defaultValue: 'Sources' }),
    });
    downloadCsv(csv, quantitiesCsvName(projectName));
  }, [rows, groupLabelFor, groupColumnHeader, projectName, t]);

  const activeDocName = useMemo(() => {
    if (!docFilter) return '';
    const doc = (docsQuery.data ?? []).find((d) => d.id === docFilter);
    return doc?.filename ?? docFilter;
  }, [docFilter, docsQuery.data]);

  /* ── States ───────────────────────────────────────────────────────── */

  const isLoading = measureQuery.isLoading || boqQuery.isLoading;
  const bothError = measureQuery.isError && boqQuery.isError;
  const partialError =
    !bothError && (measureQuery.isError || boqQuery.isError) && records.length > 0;
  const isEmpty = !isLoading && !bothError && records.length === 0;

  const dimensions: Array<{ id: RollupDimension; label: string }> = [
    { id: 'unit', label: t('quantities.by_unit', { defaultValue: 'By unit' }) },
    { id: 'trade', label: t('quantities.by_trade', { defaultValue: 'By trade' }) },
    { id: 'kind', label: t('quantities.by_type', { defaultValue: 'By type' }) },
    { id: 'source', label: t('quantities.by_source', { defaultValue: 'By source' }) },
  ];

  return (
    <div className="rounded-xl border border-border-light bg-surface-primary p-6" data-guide="quantities-summary">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10">
            <Ruler size={20} className="text-oe-blue" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-content-primary">
                {t('quantities.summary_title', { defaultValue: 'Measured quantities' })}
              </h2>
              <InfoHint
                inline
                text={t('quantities.summary_info', {
                  defaultValue:
                    'A live rollup of the quantities already captured for this project - from PDF takeoff and from your BOQ - grouped so you can see totals per unit, trade, type or source. It is read-only: measure on the takeoff canvas or edit the BOQ to change the numbers.',
                })}
              />
            </div>
            <p className="mt-0.5 text-sm text-content-tertiary">
              {t('quantities.summary_subtitle', {
                defaultValue:
                  'Totals rolled up from takeoff and BOQ for the active project. Same unit only, never mixed.',
              })}
            </p>
          </div>
        </div>
        <Button
          variant="secondary"
          size="sm"
          icon={<Download size={14} />}
          onClick={handleExport}
          disabled={rows.length === 0}
        >
          {t('quantities.export_csv', { defaultValue: 'Export CSV' })}
        </Button>
      </div>

      {/* Flow strip */}
      <div className="mt-4">
        <FlowStrip />
      </div>

      {/* Body */}
      {!projectId ? (
        <EmptyState
          className="py-10"
          icon={<Layers3 size={26} />}
          title={t('quantities.no_project_title', {
            defaultValue: 'Choose a project to see its quantities',
          })}
          description={t('quantities.no_project_desc', {
            defaultValue:
              'Measured quantities are rolled up per project. Pick or create a project, then measure a drawing or add BOQ lines.',
          })}
          action={{
            label: t('quantities.go_to_projects', { defaultValue: 'Go to projects' }),
            onClick: () => navigate('/projects'),
          }}
        />
      ) : bothError ? (
        <div className="mt-5">
          <ErrorState
            title={t('quantities.error_title', { defaultValue: 'Could not load quantities' })}
            hint={t('quantities.error_hint', {
              defaultValue: 'Check your connection and try again. Takeoff and BOQ data are both unavailable right now.',
            })}
            onRetry={() => {
              measureQuery.refetch();
              boqQuery.refetch();
            }}
          />
        </div>
      ) : isLoading && records.length === 0 ? (
        <div className="mt-5 space-y-3">
          <div className="flex gap-3">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} height={64} className="flex-1" />
            ))}
          </div>
          <Skeleton height={200} />
        </div>
      ) : isEmpty ? (
        <EmptyState
          className="py-10"
          icon={<Layers3 size={26} />}
          title={t('quantities.empty_title', { defaultValue: 'No measured quantities yet' })}
          description={t('quantities.empty_desc', {
            defaultValue:
              'Measure a drawing in PDF takeoff, extract a CAD / BIM model, or add priced lines in the BOQ. Anything you capture shows up here, grouped and totalled.',
          })}
          action={
            <div className="flex flex-wrap items-center justify-center gap-2">
              <Button
                variant="primary"
                size="sm"
                icon={<Ruler size={14} />}
                onClick={() => navigate('/takeoff')}
              >
                {t('quantities.empty_open_takeoff', { defaultValue: 'Open PDF takeoff' })}
              </Button>
              <Button
                variant="secondary"
                size="sm"
                icon={<Table2 size={14} />}
                onClick={() => navigate('/boq')}
              >
                {t('quantities.empty_open_boq', { defaultValue: 'Open BOQ editor' })}
              </Button>
            </div>
          }
        />
      ) : (
        <>
          {partialError && (
            <p className="mt-4 rounded-lg bg-semantic-warning-bg px-3 py-2 text-xs text-content-secondary">
              {measureQuery.isError
                ? t('quantities.partial_takeoff', {
                    defaultValue: 'Takeoff quantities could not be loaded; showing BOQ quantities only.',
                  })
                : t('quantities.partial_boq', {
                    defaultValue: 'BOQ quantities could not be loaded; showing takeoff quantities only.',
                  })}
            </p>
          )}

          {/* KPI strip: per-unit grand totals */}
          <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {unitTotals.slice(0, 8).map((u) => (
              <div
                key={u.unit}
                className="rounded-xl border border-border-light bg-surface-secondary/40 px-3 py-2.5"
              >
                <div className="text-2xs font-medium uppercase tracking-wide text-content-quaternary">
                  {u.unit === NO_UNIT ? t('quantities.no_unit', { defaultValue: 'No unit' }) : u.unit}
                </div>
                <div className="mt-0.5 text-lg font-semibold text-content-primary tabular-nums">
                  <QuantityDisplay
                    value={u.total}
                    unit={u.unit === NO_UNIT ? '' : u.unit}
                    precision={2}
                  />
                </div>
                <div className="text-2xs text-content-tertiary">
                  {t('quantities.kpi_count', {
                    defaultValue: '{{count}} measured',
                    count: u.count,
                  })}
                </div>
              </div>
            ))}
          </div>

          {/* Controls: group-by + filters */}
          <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-3">
            <div className="inline-flex rounded-lg border border-border-light bg-surface-secondary/40 p-0.5">
              {dimensions.map((d) => (
                <button
                  key={d.id}
                  onClick={() => setDimension(d.id)}
                  className={clsx(
                    'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                    dimension === d.id
                      ? 'bg-surface-primary text-content-primary shadow-xs'
                      : 'text-content-tertiary hover:text-content-secondary',
                  )}
                >
                  {d.label}
                </button>
              ))}
            </div>

            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <span className="inline-flex items-center gap-1 text-2xs uppercase tracking-wide text-content-quaternary">
                <Filter size={11} />
                {t('quantities.filters', { defaultValue: 'Filters' })}
              </span>
              <FilterSelect
                label={t('quantities.col_source', { defaultValue: 'Source' })}
                value={sourceFilter}
                onChange={(v) => setSourceFilter(v as '' | QuantitySource)}
                options={[
                  { value: '', label: t('quantities.filter_all', { defaultValue: 'All' }) },
                  { value: 'takeoff', label: sourceLabel('takeoff') },
                  { value: 'boq', label: sourceLabel('boq') },
                ]}
              />
              <FilterSelect
                label={t('quantities.col_unit', { defaultValue: 'Unit' })}
                value={unitFilter}
                onChange={setUnitFilter}
                options={[
                  { value: '', label: t('quantities.filter_all', { defaultValue: 'All' }) },
                  ...unitOptions.map((u) => ({
                    value: u,
                    label: u === NO_UNIT ? t('quantities.no_unit', { defaultValue: 'No unit' }) : u,
                  })),
                ]}
              />
              <FilterSelect
                label={t('quantities.col_trade', { defaultValue: 'Trade / group' })}
                value={tradeFilter}
                onChange={setTradeFilter}
                options={[
                  { value: '', label: t('quantities.filter_all', { defaultValue: 'All' }) },
                  ...tradeOptions.map((tr) => ({ value: tr, label: tr })),
                ]}
              />
              {hasActiveFilters && (
                <button
                  onClick={resetFilters}
                  className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-2xs font-medium text-content-tertiary hover:bg-surface-secondary hover:text-content-secondary transition-colors"
                >
                  <RotateCcw size={11} />
                  {t('quantities.reset_filters', { defaultValue: 'Reset' })}
                </button>
              )}
            </div>
          </div>

          {/* Active document filter chip */}
          {docFilter && (
            <div className="mt-3">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-oe-blue/10 px-2.5 py-1 text-xs font-medium text-oe-blue">
                <FileText size={12} />
                {t('quantities.filtered_to_doc', {
                  defaultValue: 'Document: {{name}}',
                  name: activeDocName,
                })}
                <button
                  onClick={() => setDocFilter(null)}
                  aria-label={t('quantities.clear_doc_filter', { defaultValue: 'Clear document filter' })}
                  className="ml-0.5 rounded-full p-0.5 hover:bg-oe-blue/20 transition-colors"
                >
                  <X size={12} />
                </button>
              </span>
            </div>
          )}

          {/* Rollup table */}
          {rows.length === 0 ? (
            <div className="mt-5 rounded-lg border border-dashed border-border-light py-8 text-center text-sm text-content-tertiary">
              {t('quantities.no_rows_for_filter', {
                defaultValue: 'No quantities match the current filters.',
              })}
            </div>
          ) : (
            <div className="mt-5 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-light text-left text-xs text-content-tertiary">
                    <th className="pb-2 pr-4 font-medium">
                      {t('quantities.col_unit', { defaultValue: 'Unit' })}
                    </th>
                    <th className="pb-2 pr-4 font-medium text-right">
                      {t('quantities.col_measurements', { defaultValue: 'Measurements' })}
                    </th>
                    <th className="pb-2 pr-4 font-medium text-right">
                      {t('quantities.col_total', { defaultValue: 'Total quantity' })}
                    </th>
                    <th className="pb-2 font-medium">
                      {t('quantities.col_sources', { defaultValue: 'Sources' })}
                    </th>
                  </tr>
                </thead>
                {dimension === 'unit' ? (
                  <tbody>
                    {rows.map((row) => (
                      <RollupTableRow key={row.unit} row={row} sourceLabel={sourceLabel} />
                    ))}
                  </tbody>
                ) : (
                  grouped.map((section) => (
                    <tbody key={section.group}>
                      <tr className="bg-surface-secondary/40">
                        <td colSpan={4} className="px-1 py-1.5">
                          <span className="text-xs font-semibold text-content-secondary">
                            {groupLabelFor(section.group)}
                          </span>
                          <span className="ml-2 text-2xs text-content-quaternary">
                            {t('quantities.group_count', {
                              defaultValue: '{{count}} measured',
                              count: section.rows.reduce((sum, r) => sum + r.count, 0),
                            })}
                          </span>
                        </td>
                      </tr>
                      {section.rows.map((row) => (
                        <RollupTableRow
                          key={`${section.group}-${row.unit}`}
                          row={row}
                          sourceLabel={sourceLabel}
                        />
                      ))}
                    </tbody>
                  ))
                )}
              </table>
            </div>
          )}

          {/* Document filter picker (only when a doc actually carries measurements) */}
          {docOptions.length > 0 && !docFilter && (
            <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border-light pt-3">
              <span className="text-2xs uppercase tracking-wide text-content-quaternary">
                {t('quantities.focus_document', { defaultValue: 'Focus one document' })}
              </span>
              {docOptions.slice(0, 6).map((d) => (
                <button
                  key={d.id}
                  onClick={() => setDocFilter(d.id)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border-light bg-surface-primary px-2.5 py-1 text-xs text-content-secondary hover:border-oe-blue/40 hover:text-content-primary transition-colors"
                >
                  <FileText size={12} className="text-content-quaternary" />
                  <span className="max-w-[160px] truncate">{d.filename}</span>
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
