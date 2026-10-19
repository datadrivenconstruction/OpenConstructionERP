// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The records behind one project's value in one benchmark group. The totals at
// the top are summed by the server over every record, so they equal the value
// in the table, including after unit or currency conversion; the list below is
// paged and links each record to its bill position.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ExternalLink } from 'lucide-react';
import { Button, EmptyState, SideDrawer, Skeleton } from '@/shared/ui';
import { fmtNumber } from '@/shared/lib/formatters';
import {
  costIndexOf,
  drillDimensions,
  fetchDrilldown,
  toNumber,
  type PerformanceBenchmarkRequest,
  type PerformanceGroup,
  type PerformanceProjectRow,
} from './performance';
import { fmtValue, prettyUnit } from './performanceFormat';

const PAGE = 50;

export interface DrillTarget {
  group: PerformanceGroup;
  row: PerformanceProjectRow;
  projectName: string;
}

export function PerformanceDrilldown({
  target,
  request,
  kpiLabel,
  onClose,
}: {
  target: DrillTarget | null;
  request: PerformanceBenchmarkRequest;
  kpiLabel: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [offset, setOffset] = useState(0);
  const body = target
    ? {
        kpi: request.kpi,
        project_id: target.row.project_id,
        row_filters: request.row_filters,
        period_start: request.period_start,
        period_end: request.period_end,
        split_by: request.split_by ?? null,
        dimensions: drillDimensions(target.group, target.row),
        target_unit: target.group.dimensions.unit ?? null,
        reporting_currency: request.reporting_currency ?? null,
        ...costIndexOf(request),
        offset,
        limit: PAGE,
      }
    : null;
  const query = useQuery({
    queryKey: ['analytics', 'performance', 'drilldown', body],
    queryFn: () => fetchDrilldown(body!),
    enabled: Boolean(body),
  });
  const data = query.data;
  const close = () => {
    setOffset(0);
    onClose();
  };
  const unit = prettyUnit(data?.value_unit ?? target?.group.value_unit ?? '');

  return (
    <SideDrawer
      open={Boolean(target)}
      onClose={close}
      title={t('analytics.perf.drill_title', { defaultValue: 'Where this value comes from' })}
      subtitle={target ? `${target.projectName} · ${kpiLabel}` : undefined}
      widthClass="max-w-2xl"
    >
      {query.isLoading ? (
        <div className="space-y-2 p-4">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-32 w-full" />
        </div>
      ) : query.isError || !data ? (
        <EmptyState
          title={t('analytics.perf.drill_error', { defaultValue: 'Could not load the records' })}
          action={
            <Button variant="secondary" size="sm" onClick={() => query.refetch()}>
              {t('analytics.retry', { defaultValue: 'Retry' })}
            </Button>
          }
        />
      ) : (
        <div className="space-y-3 p-4 text-sm">
          <div className="grid grid-cols-2 gap-3 rounded-lg bg-surface-secondary p-3 text-xs sm:grid-cols-4">
            <DrillFigure label={t('analytics.perf.col_value', { defaultValue: 'Value' })} value={`${fmtValue(data.value) ?? '-'} ${unit}`} />
            <DrillFigure label={t('analytics.perf.col_numerator', { defaultValue: 'Numerator' })} value={fmtValue(data.numerator) ?? '-'} />
            <DrillFigure label={t('analytics.perf.col_denominator', { defaultValue: 'Denominator' })} value={fmtValue(data.denominator) ?? '-'} />
            <DrillFigure label={t('analytics.perf.col_records', { defaultValue: 'Records' })} value={String(data.total_records)} />
          </div>
          <p className="text-2xs text-content-tertiary">
            {t('analytics.perf.drill_hint', {
              defaultValue:
                'The totals are summed over every record below and match the value in the table. Figures in brackets are as counted after unit, currency or cost index conversion.',
            })}
          </p>
          {data.records.length === 0 ? (
            <p className="text-content-secondary">
              {t('analytics.perf.drill_empty', { defaultValue: 'No records match this value.' })}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border-light text-left text-content-tertiary">
                    <th className="py-1 pe-2 font-medium">{t('analytics.perf.drill_record', { defaultValue: 'Record' })}</th>
                    <th className="px-2 py-1 text-right font-medium">{t('analytics.perf.col_numerator', { defaultValue: 'Numerator' })}</th>
                    <th className="px-2 py-1 text-right font-medium">{t('analytics.perf.col_denominator', { defaultValue: 'Denominator' })}</th>
                    <th className="py-1 ps-2 font-medium">{t('analytics.perf.drill_unit', { defaultValue: 'Unit' })}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.records.map((r) => {
                    const label = [r.ref, r.description].filter(Boolean).join(' ') || r.record_id;
                    const converted =
                      r.counted_denominator !== null &&
                      r.counted_denominator !== undefined &&
                      String(r.counted_denominator) !== String(r.denominator);
                    const restated =
                      r.counted_numerator !== null &&
                      r.counted_numerator !== undefined &&
                      String(r.counted_numerator) !== String(r.numerator);
                    const factor = toNumber(r.index_factor ?? null);
                    return (
                      <tr key={r.record_id} className="border-b border-border-light last:border-0">
                        <td className="max-w-[18rem] py-1 pe-2">
                          {r.boq_id && r.position_id ? (
                            <Link
                              to={`/boq/${r.boq_id}?highlight=${r.position_id}`}
                              className="inline-flex max-w-full items-center gap-1 text-oe-blue hover:underline"
                              title={label}
                            >
                              <span className="truncate">{label}</span>
                              <ExternalLink size={11} className="shrink-0" />
                            </Link>
                          ) : (
                            <span className="block truncate" title={label}>
                              {label}
                            </span>
                          )}
                        </td>
                        <td className="px-2 py-1 text-right tabular-nums">
                          {fmtValue(r.numerator) ?? '-'}
                          {restated && (
                            <span className="ms-1 text-content-tertiary">({fmtValue(r.counted_numerator)})</span>
                          )}
                          {factor !== null && factor !== 1 && (
                            <div className="text-2xs text-content-tertiary">
                              {t('analytics.perf.factor_times', {
                                defaultValue: 'x{{factor}}',
                                factor: fmtNumber(factor, 4),
                              })}
                            </div>
                          )}
                        </td>
                        <td className="px-2 py-1 text-right tabular-nums">
                          {fmtValue(r.denominator) ?? '-'}
                          {converted && (
                            <span className="ms-1 text-content-tertiary">({fmtValue(r.counted_denominator)})</span>
                          )}
                        </td>
                        <td className="py-1 ps-2">{prettyUnit(r.dimensions.unit ?? r.dimensions.currency ?? '')}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {data.total_records > PAGE && (
            <div className="flex items-center justify-between text-xs text-content-secondary">
              <Button variant="ghost" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                {t('analytics.perf.drill_prev', { defaultValue: 'Previous' })}
              </Button>
              <span>
                {t('analytics.perf.drill_page', {
                  defaultValue: '{{from}}-{{to}} of {{total}}',
                  from: offset + 1,
                  to: Math.min(offset + PAGE, data.total_records),
                  total: data.total_records,
                })}
              </span>
              <Button
                variant="ghost"
                size="sm"
                disabled={offset + PAGE >= data.total_records}
                onClick={() => setOffset(offset + PAGE)}
              >
                {t('analytics.perf.drill_next', { defaultValue: 'Next' })}
              </Button>
            </div>
          )}
        </div>
      )}
    </SideDrawer>
  );
}

function DrillFigure({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-content-tertiary">{label}</div>
      <div className="truncate font-semibold tabular-nums text-content-primary" title={value}>
        {value}
      </div>
    </div>
  );
}
