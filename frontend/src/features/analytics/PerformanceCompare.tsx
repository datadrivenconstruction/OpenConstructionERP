// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Several KPIs side by side over the same projects: one row per project, one
// column per KPI and unit (a KPI read in m² and in m³ is two columns, never a
// sum). The last row is each column's benchmark. Exported as CSV or Excel
// exactly as shown, with numbers left as numbers.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Columns3, Download, FileSpreadsheet } from 'lucide-react';
import { Badge, Button, Card, Skeleton } from '@/shared/ui';
import { compareNames } from '@/shared/lib/collator';
import { useToastStore } from '@/stores/useToastStore';
import {
  NULL_GROUP_KEY,
  buildCompareMatrix,
  costIndexOf,
  downloadCsv,
  downloadMatrixXlsx,
  fetchPerformanceCompare,
  matrixToCsv,
  toNumber,
  type PerformanceBenchmarkRequest,
  type PerformanceCompareColumn,
  type PerformanceCompareRequest,
} from './performance';
import { fmtValue, prettyUnit } from './performanceFormat';

const MAX_KPIS = 8;

export function PerformanceCompare({
  kpiKeys,
  kpiLabel,
  request,
  initial,
}: {
  kpiKeys: string[];
  kpiLabel: (key: string) => string;
  request: PerformanceBenchmarkRequest;
  initial: string;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [chosen, setChosen] = useState<string[]>(() => [initial]);
  const [exporting, setExporting] = useState(false);

  const body: PerformanceCompareRequest = useMemo(
    () => ({
      project_ids: request.project_ids,
      clients: request.clients,
      regions: request.regions,
      project_types: request.project_types,
      statuses: request.statuses,
      row_filters: request.row_filters,
      period_start: request.period_start,
      period_end: request.period_end,
      kpis: chosen,
      convert_units: request.convert_units,
      min_projects: request.min_projects,
      min_records: request.min_records,
      statistic: request.statistic,
      reporting_currency: request.reporting_currency ?? null,
      ...costIndexOf(request),
    }),
    [request, chosen],
  );
  const query = useQuery({
    queryKey: ['analytics', 'performance', 'compare', body],
    queryFn: () => fetchPerformanceCompare(body),
    enabled: chosen.length > 0,
  });
  const data = query.data;

  const columnLabel = (c: PerformanceCompareColumn) => {
    const unit = c.group.value_unit ?? Object.values(c.group.dimensions).filter((v) => v && v !== NULL_GROUP_KEY).join(' / ');
    return unit ? `${kpiLabel(c.kpi)} (${prettyUnit(unit)})` : kpiLabel(c.kpi);
  };
  const projects = useMemo(
    () => [...(data?.projects ?? [])].sort((a, b) => compareNames(a.name, b.name)),
    [data],
  );
  const toggle = (key: string) =>
    setChosen((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : prev.length >= MAX_KPIS ? prev : [...prev, key],
    );

  const matrix = () =>
    data
      ? buildCompareMatrix(
          { ...data, projects },
          {
            project: t('analytics.perf.col_project', { defaultValue: 'Project' }),
            client: t('analytics.perf.col_client', { defaultValue: 'Client' }),
            region: t('analytics.perf.col_region', { defaultValue: 'Region' }),
            status: t('analytics.perf.col_project_status', { defaultValue: 'Project status' }),
            column: columnLabel,
            benchmark: t('analytics.perf.compare_benchmark_row', { defaultValue: 'Benchmark' }),
          },
        )
      : [];
  const exportXlsx = async () => {
    setExporting(true);
    try {
      await downloadMatrixXlsx(matrix(), 'performance_comparison.xlsx', t('analytics.perf.compare_title', { defaultValue: 'Compare KPIs' }));
    } catch (err) {
      addToast({
        type: 'error',
        title: t('analytics.perf.export_failed', { defaultValue: 'Could not export' }),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setExporting(false);
    }
  };

  return (
    <Card data-testid="analytics-performance-compare">
      <div className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h3 className="flex items-center gap-2 text-base font-semibold text-content-primary">
              <Columns3 size={16} />
              {t('analytics.perf.compare_title', { defaultValue: 'Compare KPIs' })}
            </h3>
            <p className="mt-1 text-xs text-content-secondary">
              {t('analytics.perf.compare_hint', {
                defaultValue:
                  'Up to eight KPIs side by side over the projects above. A KPI read in more than one unit gets one column per unit. The last row is each column’s benchmark.',
              })}
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              icon={<Download size={14} />}
              disabled={!data || !data.columns.length}
              onClick={() => downloadCsv(matrixToCsv(matrix()), 'performance_comparison.csv')}
            >
              {t('analytics.perf.export_csv', { defaultValue: 'Export CSV' })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={<FileSpreadsheet size={14} />}
              disabled={!data || !data.columns.length || exporting}
              onClick={exportXlsx}
            >
              {t('analytics.perf.export_xlsx', { defaultValue: 'Export Excel' })}
            </Button>
          </div>
        </div>
        <div className="flex flex-wrap gap-1">
          {kpiKeys.map((key) => {
            const on = chosen.includes(key);
            return (
              <button
                key={key}
                type="button"
                onClick={() => toggle(key)}
                disabled={!on && chosen.length >= MAX_KPIS}
                aria-pressed={on}
                className={`rounded-full border px-2 py-0.5 text-xs transition-colors disabled:opacity-40 ${
                  on
                    ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                    : 'border-border-light text-content-secondary hover:border-oe-blue'
                }`}
              >
                {kpiLabel(key)}
              </button>
            );
          })}
        </div>
        {chosen.length === 0 ? (
          <p className="text-xs text-content-tertiary">
            {t('analytics.perf.compare_pick', { defaultValue: 'Pick at least one KPI to compare.' })}
          </p>
        ) : query.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : query.isError ? (
          <p className="text-xs text-semantic-error">
            {t('analytics.perf.error', { defaultValue: 'Could not load the benchmark' })}
          </p>
        ) : !data || data.columns.length === 0 ? (
          <p className="text-xs text-content-tertiary">
            {t('analytics.perf.empty_title', { defaultValue: 'No data for this KPI yet' })}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border-light text-left text-content-tertiary">
                  <th className="py-2 pe-3 font-medium">{t('analytics.perf.col_project', { defaultValue: 'Project' })}</th>
                  {data.columns.map((c) => (
                    <th key={`${c.kpi}|${c.group.key}`} className="px-3 py-2 text-right font-medium">
                      {columnLabel(c)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {projects.map((p) => (
                  <tr key={p.project_id} className="border-b border-border-light">
                    <td className="max-w-[16rem] truncate py-1.5 pe-3">
                      <Link to={`/projects/${p.project_id}`} className="text-content-primary hover:text-oe-blue hover:underline">
                        {p.name}
                      </Link>
                    </td>
                    {data.columns.map((c) => {
                      const row = c.group.rows.find((r) => r.project_id === p.project_id);
                      const value = fmtValue(row?.value);
                      const variance = toNumber(row?.variance);
                      return (
                        <td key={`${c.kpi}|${c.group.key}`} className="px-3 py-1.5 text-right tabular-nums">
                          {value ?? <span className="text-content-tertiary">-</span>}
                          {variance !== null && Math.abs(variance) >= 0.25 && (
                            <Badge variant="warning" size="sm" className="ms-1">
                              {variance > 0 ? '▲' : '▼'}
                            </Badge>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
                <tr className="bg-surface-secondary font-semibold">
                  <td className="py-1.5 pe-3">{t('analytics.perf.compare_benchmark_row', { defaultValue: 'Benchmark' })}</td>
                  {data.columns.map((c) => (
                    <td key={`${c.kpi}|${c.group.key}`} className="px-3 py-1.5 text-right tabular-nums">
                      {fmtValue(c.group.headline ?? c.group.benchmark.weighted) ?? '-'}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
            <p className="mt-1 text-2xs text-content-tertiary">
              {t('analytics.perf.compare_marker_hint', {
                defaultValue: '▲ ▼ marks a project 25 % or more above or below the column’s benchmark.',
              })}
            </p>
          </div>
        )}
      </div>
    </Card>
  );
}
