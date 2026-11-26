// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// CostTypeGridPanel - budget, committed, actual, forecast, EAC and variance per
// cost code, split by cost type (labor, material, equipment, subcontractor,
// other). Reads GET /costmodel/projects/{id}/5d/cost-type-grid/.
//
// Money note: every figure arrives as a Decimal-encoded STRING and cells that
// hold several budget lines are added with exact decimal strings, never floats.
// Every figure carries its source in its tooltip; nothing is invented, and an
// empty grid says what to add.

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Inbox, Layers } from 'lucide-react';

import { Card, Skeleton, EmptyState, Badge } from '@/shared/ui';
import { fmtCurrency } from '@/shared/lib/formatters';
import { getErrorMessage } from '@/shared/lib/api';
import { sumMoneyStrings } from '@/shared/lib/exactDecimal';
import {
  costTypeGridKey,
  fetchCostTypeGrid,
  type CostTypeGrid,
  type CostTypeGridRow,
  type CostTypeGridTotals,
} from './costTypeGridApi';

export interface CostTypeGridPanelProps {
  projectId: string;
  /** Project currency, used until the grid answers. */
  currency?: string;
}

/** Column bucket for lines whose category is outside the cost-type vocabulary. */
export const UNCLASSIFIED = 'unclassified';

const METRICS = ['budget', 'committed', 'actual', 'forecast', 'eac', 'variance'] as const;
type Metric = (typeof METRICS)[number];

/** The column a row belongs to: its cost type, else the unclassified bucket. */
export function columnOf(row: CostTypeGridRow, costTypes: readonly string[]): string {
  return row.cost_type && costTypes.includes(row.cost_type) ? row.cost_type : UNCLASSIFIED;
}

/** Exact per-metric sums of a set of grid rows. */
export function sumRows(rows: readonly CostTypeGridTotals[]): CostTypeGridTotals {
  const out = {} as CostTypeGridTotals;
  for (const metric of METRICS) out[metric] = sumMoneyStrings(rows.map((r) => r[metric]));
  return out;
}

function isNegative(value: string): boolean {
  return value.trim().startsWith('-') && Number(value) !== 0;
}

export function CostTypeGridPanel({ projectId, currency }: CostTypeGridPanelProps) {
  const { t } = useTranslation();

  const { data, isLoading, error } = useQuery({
    queryKey: costTypeGridKey(projectId),
    queryFn: () => fetchCostTypeGrid(projectId),
    retry: false,
  });

  const resolvedCurrency = data?.currency || currency || '';

  const typeLabels = useMemo<Record<string, string>>(
    () => ({
      labor: t('costmodel.cat_labor', { defaultValue: 'Labor' }),
      material: t('costmodel.cat_material', { defaultValue: 'Material' }),
      equipment: t('costmodel.cat_equipment', { defaultValue: 'Equipment' }),
      subcontractor: t('costmodel.cat_subcontractor', { defaultValue: 'Subcontractor' }),
      other: t('costmodel.cat_other', { defaultValue: 'Other' }),
      [UNCLASSIFIED]: t('costmodel.ctg_unclassified', { defaultValue: 'Unclassified' }),
    }),
    [t],
  );

  const metricLabels: Record<Metric, string> = {
    budget: t('costmodel.ctg_budget', { defaultValue: 'Budget' }),
    committed: t('costmodel.committed', { defaultValue: 'Committed' }),
    actual: t('costmodel.actual', { defaultValue: 'Actual' }),
    forecast: t('costmodel.forecast', { defaultValue: 'Forecast' }),
    eac: t('costmodel.ctg_eac', { defaultValue: 'EAC' }),
    variance: t('costmodel.variance', { defaultValue: 'Variance' }),
  };

  const view = useMemo(() => (data ? buildView(data) : null), [data]);

  /** Where one cell's figure comes from, for its tooltip. */
  const sourceOf = (rows: CostTypeGridRow[], metric: Metric): string => {
    if (rows.length === 0) return '';
    const parts = rows.map((row) => {
      const lead = row.description || row.cost_code;
      switch (metric) {
        case 'budget':
          if (row.split_basis === 'resources') {
            return `${lead}: ${t('costmodel.ctg_src_split', { defaultValue: 'Budget split from the resources of the BOQ position' })}`;
          }
          if (row.split_basis === 'no_resources') {
            return `${lead}: ${t('costmodel.ctg_src_unsplit', { defaultValue: 'The position has no resources, so its whole amount sits under Other' })}`;
          }
          return lead;
        case 'committed':
          return `${lead}: ${
            row.committed_from_documents
              ? t('costmodel.ctg_src_committed_docs', {
                  defaultValue: 'Purchase orders and subcontracts booked to this budget line',
                })
              : t('costmodel.ctg_src_committed_manual', {
                  defaultValue: 'Committed value entered on the budget line',
                })
          }`;
        case 'eac':
        case 'variance':
          return `${lead}: ${t('costmodel.ctg_src_eac', {
            defaultValue: 'EAC is the forecast, raised to committed or actual when either is higher. Here: {{basis}}',
            basis: metricLabels[row.eac_basis],
          })}`;
        default:
          return lead;
      }
    });
    return parts.join('\n');
  };

  if (isLoading) {
    return (
      <Card>
        <div className="space-y-3">
          <Skeleton height={32} className="w-1/3" rounded="md" />
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} height={40} className="w-full" rounded="md" />
          ))}
        </div>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <div className="flex items-start gap-3 rounded-lg border border-semantic-error/30 bg-semantic-error-bg/30 p-3">
          <AlertTriangle size={20} className="mt-0.5 shrink-0 text-semantic-error" />
          <div>
            <p className="text-sm font-medium text-content-primary">
              {t('costmodel.ctg_load_failed', { defaultValue: 'Could not load the cost type grid' })}
            </p>
            <p className="mt-0.5 text-xs text-content-tertiary">{getErrorMessage(error)}</p>
          </div>
        </div>
      </Card>
    );
  }

  const columns = view?.columns ?? [];

  return (
    <Card padding="none" data-testid="cost-type-grid">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-light px-5 py-4">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue-text">
            <Layers size={16} />
          </div>
          <div>
            <h3 className="oe-section-title">{t('costmodel.ctg_title', { defaultValue: 'By cost type' })}</h3>
            <p className="text-xs text-content-tertiary">
              {t('costmodel.ctg_subtitle', {
                defaultValue:
                  'Budget, committed, actual and forecast for each cost code, split into labor, material, equipment, subcontractor and other.',
              })}
            </p>
          </div>
        </div>
        {resolvedCurrency && (
          <Badge variant="neutral" size="sm">
            {resolvedCurrency}
          </Badge>
        )}
      </div>

      {!data || data.groups.length === 0 ? (
        <div className="p-6">
          <EmptyState
            icon={<Inbox size={28} strokeWidth={1.5} />}
            title={t('costmodel.ctg_empty_title', { defaultValue: 'No budget lines to split yet' })}
            description={t('costmodel.ctg_empty_desc', {
              defaultValue:
                'Generate a budget from your BOQ. Each position becomes one budget line per cost type, cut by its resources.',
            })}
          />
        </div>
      ) : (
        <div className="space-y-4 p-5">
          {data.findings.length > 0 && (
            <div role="status" className="rounded-xl border border-semantic-warning/30 bg-semantic-warning/10 p-3">
              <p className="mb-1 text-xs font-semibold text-content-primary">
                {t('costmodel.ctg_findings', { defaultValue: 'Cost type checks' })}
              </p>
              <ul className="space-y-0.5 text-xs text-content-secondary">
                {data.findings.slice(0, 8).map((f, i) => (
                  <li key={`${f.rule_id}-${f.element_ref ?? i}`}>{f.message}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="overflow-x-auto">
            <table className="oe-table w-full text-xs">
              <thead>
                <tr>
                  <th scope="col" rowSpan={2} className="sticky left-0 z-10 bg-surface-primary pr-4 text-left">
                    {t('costmodel.ctg_code', { defaultValue: 'Cost code' })}
                  </th>
                  {columns.map((col) => (
                    <th
                      key={col}
                      scope="colgroup"
                      colSpan={METRICS.length}
                      className="border-l border-border-light text-center"
                    >
                      {typeLabels[col] ?? col}
                    </th>
                  ))}
                  <th scope="colgroup" colSpan={METRICS.length} className="border-l border-border-light text-center">
                    {t('common.total', { defaultValue: 'Total' })}
                  </th>
                </tr>
                <tr>
                  {[...columns, 'total'].map((col) =>
                    METRICS.map((m, i) => (
                      <th
                        key={`${col}-${m}`}
                        scope="col"
                        className={`text-right font-medium ${i === 0 ? 'border-l border-border-light' : ''}`}
                      >
                        {metricLabels[m]}
                      </th>
                    )),
                  )}
                </tr>
              </thead>
              <tbody>
                {view?.groups.map((group) => (
                  <tr key={group.cost_code || '__none'}>
                    <td className="sticky left-0 z-10 bg-surface-primary pr-4 font-medium">
                      <span>{group.cost_code || t('boq.uncategorized', { defaultValue: '(Not specified)' })}</span>
                      {group.cost_code_title && (
                        <span className="block max-w-[200px] truncate text-2xs font-normal text-content-tertiary">
                          {group.cost_code_title}
                        </span>
                      )}
                    </td>
                    {columns.map((col) => {
                      const rows = group.byColumn[col] ?? [];
                      const sums = rows.length > 0 ? sumRows(rows) : null;
                      return METRICS.map((m, i) => (
                        <td
                          key={`${col}-${m}`}
                          title={sourceOf(rows, m) || undefined}
                          className={`text-right tabular-nums ${i === 0 ? 'border-l border-border-light' : ''} ${
                            sums && m === 'variance' && isNegative(sums[m])
                              ? 'text-semantic-error'
                              : 'text-content-secondary'
                          }`}
                        >
                          {sums ? fmtCurrency(sums[m], resolvedCurrency) : ''}
                        </td>
                      ));
                    })}
                    {METRICS.map((m, i) => (
                      <td
                        key={`total-${m}`}
                        className={`text-right font-medium tabular-nums ${i === 0 ? 'border-l border-border-light' : ''} ${
                          m === 'variance' && isNegative(group.subtotal[m]) ? 'text-semantic-error' : ''
                        }`}
                      >
                        {fmtCurrency(group.subtotal[m], resolvedCurrency)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td className="sticky left-0 z-10 bg-surface-primary pr-4">
                    {t('common.total', { defaultValue: 'Total' })}
                  </td>
                  {columns.map((col) =>
                    METRICS.map((m, i) => (
                      <td
                        key={`${col}-${m}`}
                        className={`text-right tabular-nums ${i === 0 ? 'border-l border-border-light' : ''}`}
                      >
                        {fmtCurrency(view?.columnTotals[col]?.[m], resolvedCurrency)}
                      </td>
                    )),
                  )}
                  {METRICS.map((m, i) => (
                    <td
                      key={`total-${m}`}
                      className={`text-right tabular-nums ${i === 0 ? 'border-l border-border-light' : ''} ${
                        m === 'variance' && isNegative(data.total[m]) ? 'text-semantic-error' : ''
                      }`}
                    >
                      {fmtCurrency(data.total[m], resolvedCurrency)}
                    </td>
                  ))}
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
      )}
    </Card>
  );
}

interface GridView {
  /** Column buckets in display order; the unclassified one only when a line needs it. */
  columns: string[];
  groups: {
    cost_code: string;
    cost_code_title: string;
    byColumn: Record<string, CostTypeGridRow[]>;
    subtotal: CostTypeGridTotals;
  }[];
  columnTotals: Record<string, CostTypeGridTotals>;
}

/** Lay the grid out as cost code rows x cost type columns. */
export function buildView(grid: CostTypeGrid): GridView {
  const known = grid.cost_types;
  const byColumn: Record<string, CostTypeGridRow[]> = {};
  const groups = grid.groups.map((group) => {
    const cells: Record<string, CostTypeGridRow[]> = {};
    for (const row of group.rows) {
      const col = columnOf(row, known);
      (cells[col] ??= []).push(row);
      (byColumn[col] ??= []).push(row);
    }
    return {
      cost_code: group.cost_code,
      cost_code_title: group.cost_code_title,
      byColumn: cells,
      subtotal: group.subtotal,
    };
  });
  const columns = byColumn[UNCLASSIFIED] ? [...known, UNCLASSIFIED] : [...known];
  const columnTotals: Record<string, CostTypeGridTotals> = {};
  for (const col of columns) columnTotals[col] = sumRows(byColumn[col] ?? []);
  return { columns, groups, columnTotals };
}
