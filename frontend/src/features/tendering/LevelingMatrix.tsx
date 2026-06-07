/**
 * Bid leveling matrix — rows = reference BOQ lines, columns = bids. Each
 * cell shows the raw vs leveled price for one (line × bidder) pair and is
 * colour-coded against the line's median across bids:
 *
 *   >1.2× median → red   (likely over-priced)
 *   <0.8× median → green (likely under-priced)
 *
 * Empty cells (the bid omitted that line) get an "imputed" badge. A
 * "Run leveling" CTA triggers the backend recompute and refreshes the
 * matrix in place.
 */

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  BarChart3,
  Building2,
  Calculator,
  Scale,
} from 'lucide-react';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  SkeletonTable,
} from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getIntlLocale } from '@/shared/lib/formatters';
import { getLevelingMatrix, levelBids } from './api';

interface Props {
  packageId: string;
  currency: string;
}

function formatNumber(n: number, decimals = 2): string {
  return new Intl.NumberFormat(getIntlLocale(), {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n);
}

function formatCurrency(amount: number, currency?: string): string {
  const code = (currency || '').trim().toUpperCase();
  if (!/^[A-Z]{3}$/.test(code)) {
    return new Intl.NumberFormat(getIntlLocale(), {
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(amount);
  }
  try {
    return new Intl.NumberFormat(getIntlLocale(), {
      style: 'currency',
      currency: code,
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    return `${amount.toFixed(0)} ${code}`;
  }
}

function median(values: number[]): number {
  const nonzero = values.filter((v) => v > 0);
  if (nonzero.length === 0) return 0;
  const sorted = [...nonzero].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[mid - 1]! + sorted[mid]!) / 2
    : sorted[mid]!;
}

function cellColorClass(value: number, rowMedian: number): string {
  if (value <= 0 || rowMedian <= 0) return 'text-content-primary';
  const ratio = value / rowMedian;
  if (ratio > 1.2) return 'text-semantic-error font-semibold';
  if (ratio < 0.8) return 'text-semantic-success font-semibold';
  return 'text-content-primary';
}

function statusBadge(
  status: '' | 'matched' | 'scaled' | 'imputed',
  t: ReturnType<typeof useTranslation>['t'],
) {
  if (status === 'imputed') {
    return (
      <Badge variant="warning" size="sm">
        {t('tendering.leveling.imputed', 'Imputed')}
      </Badge>
    );
  }
  if (status === 'scaled') {
    return (
      <Badge variant="blue" size="sm">
        {t('tendering.leveling.scaled', 'Scaled')}
      </Badge>
    );
  }
  return null;
}

export function LevelingMatrix({ packageId, currency }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const {
    data: matrix,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['tendering-leveling-matrix', packageId],
    queryFn: () => getLevelingMatrix(packageId),
  });

  const runMutation = useMutation({
    mutationFn: () => levelBids(packageId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['tendering-leveling-matrix', packageId],
      });
      queryClient.invalidateQueries({
        queryKey: ['tendering-package', packageId],
      });
      addToast({
        type: 'success',
        title: t('tendering.leveling.run_success', {
          defaultValue: 'Bid leveling complete',
        }),
      });
    },
    onError: (error: Error) => {
      addToast({
        type: 'error',
        title: t('toasts.error', { defaultValue: 'Error' }),
        message: error.message,
      });
    },
  });

  // The matrix is computed in the package currency (authoritative). Fall back
  // to the project currency prop only when the backend did not report one.
  const matrixCurrency = matrix?.currency || currency;

  const rowMedians = useMemo(() => {
    if (!matrix) return new Map<string, number>();
    const m = new Map<string, number>();
    for (const row of matrix.rows) {
      const key = `${row.position_id ?? ''}|${row.line_code}`;
      m.set(key, median(row.cells.map((c) => c.leveled_total)));
    }
    return m;
  }, [matrix]);

  if (isLoading) {
    return (
      <div className="mt-4">
        <SkeletonTable rows={4} columns={4} />
      </div>
    );
  }

  if (isError) {
    return (
      <Card className="mt-4 py-10">
        <EmptyState
          icon={<AlertTriangle size={28} strokeWidth={1.5} />}
          title={t('common.error', { defaultValue: 'Error' })}
          description={t('tendering.leveling.load_error', {
            defaultValue:
              'Failed to load the leveling matrix. Please try again.',
          })}
        />
      </Card>
    );
  }

  return (
    <Card className="mt-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h4 className="text-sm font-semibold text-content-primary flex items-center gap-2">
            <Scale size={16} className="text-oe-blue" />
            {t('tendering.leveling.title', 'Bid Leveling')}
            {matrixCurrency && (
              <Badge variant="neutral" size="sm">
                {matrixCurrency}
              </Badge>
            )}
          </h4>
          <p className="mt-1 text-xs text-content-secondary">
            {t('tendering.leveling.subtitle', {
              defaultValue:
                'Normalize competing bids onto the reference BOQ. Omitted lines are imputed at the bidder mean rate so a short quote cannot win on price.',
            })}
          </p>
        </div>
        <Button
          variant="primary"
          size="sm"
          icon={<Calculator size={14} />}
          loading={runMutation.isPending}
          onClick={() => runMutation.mutate()}
        >
          {t('tendering.leveling.run', 'Run Leveling')}
        </Button>
      </div>

      {/* Off-currency exclusion notice — leveling normalises every bid onto
          the same reference quantities and never blends currencies, so bids
          quoted in a currency other than the package currency are dropped. */}
      {matrix && matrix.excluded_off_currency > 0 && (
        <div className="mb-4 flex items-start gap-2 rounded-lg border border-semantic-warning/30 bg-semantic-warning-bg/30 px-3 py-2 text-xs text-content-secondary">
          <AlertTriangle
            size={14}
            className="mt-0.5 shrink-0 text-semantic-warning"
          />
          <span>
            {t('tendering.leveling.excluded_currency', {
              defaultValue:
                '{{count}} bid(s) excluded: quoted in a different currency than the package ({{currency}}). Leveling never blends currencies; re-quote or FX-convert them first.',
              count: matrix.excluded_off_currency,
              currency: matrixCurrency || '-',
            })}
          </span>
        </div>
      )}

      {!matrix || matrix.rows.length === 0 ? (
        <EmptyState
          icon={<BarChart3 size={28} strokeWidth={1.5} />}
          title={t('tendering.leveling.empty_title', {
            defaultValue: 'No reference lines',
          })}
          description={t('tendering.leveling.empty_desc', {
            defaultValue:
              'Link the package to a BOQ and add bids, then run leveling to see the matrix.',
          })}
        />
      ) : (
        <>
          {/* Bid summary chips */}
          {matrix.bid_summaries.length > 0 && (
            <div className="mb-4 flex flex-wrap gap-2">
              {matrix.bid_summaries.map((bs) => (
                <div
                  key={bs.bid_id}
                  className="rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2"
                >
                  <div className="flex items-center gap-2">
                    <Building2
                      size={12}
                      className="text-content-tertiary"
                    />
                    <span className="text-xs font-semibold text-content-primary">
                      {bs.company_name}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center gap-3 text-[11px]">
                    <span className="text-content-secondary">
                      {t('tendering.leveling.raw', 'Raw')}:{' '}
                      <span className="tabular-nums text-content-primary">
                        {formatCurrency(Number(bs.raw_amount), bs.currency || matrixCurrency)}
                      </span>
                    </span>
                    <span className="text-content-secondary">
                      {t('tendering.leveling.leveled', 'Leveled')}:{' '}
                      <span className="tabular-nums font-semibold text-content-primary">
                        {formatCurrency(
                          Number(bs.leveled_amount),
                          bs.currency || matrixCurrency,
                        )}
                      </span>
                    </span>
                  </div>
                  <div className="mt-1 flex items-center gap-1.5 text-[10px] text-content-tertiary">
                    <span>{bs.matched_lines}m</span>
                    <span>·</span>
                    <span>{bs.scaled_lines}s</span>
                    <span>·</span>
                    <span>{bs.imputed_lines}i</span>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Matrix */}
          <div className="overflow-x-auto relative">
            <table className="w-full text-sm">
              <thead className="sticky top-0 z-10 bg-surface-primary">
                <tr className="border-b border-border-light">
                  <th className="whitespace-nowrap px-3 py-2.5 text-left font-semibold text-content-primary sticky left-0 z-20 bg-surface-primary">
                    {t('tendering.leveling.line', 'Line')}
                  </th>
                  <th className="whitespace-nowrap px-3 py-2.5 text-right font-semibold text-content-primary">
                    {t('tendering.leveling.reference', 'Reference')}
                  </th>
                  {matrix.bid_summaries.map((bs) => (
                    <th
                      key={bs.bid_id}
                      className="whitespace-nowrap px-3 py-2.5 text-right font-semibold text-content-primary"
                    >
                      <span className="flex items-center justify-end gap-1.5">
                        <Building2
                          size={12}
                          className="text-content-tertiary"
                        />
                        {bs.company_name}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {matrix.rows.map((row, idx) => {
                  const key = `${row.position_id ?? ''}|${row.line_code}`;
                  const m = rowMedians.get(key) ?? 0;
                  return (
                    <tr
                      key={`${key}-${idx}`}
                      className="group border-b border-border-light/50 transition-colors hover:bg-surface-secondary/30"
                    >
                      <td className="px-3 py-2.5 sticky left-0 bg-surface-primary group-hover:bg-surface-secondary/30">
                        {row.line_code && (
                          <span className="text-xs text-content-tertiary mr-2 tabular-nums">
                            {row.line_code}
                          </span>
                        )}
                        <span className="text-content-primary">
                          {row.description || '-'}
                        </span>
                        <span className="ml-2 text-xs text-content-tertiary">
                          {formatNumber(row.reference_quantity)} {row.unit}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-content-secondary">
                        {formatNumber(row.reference_total)}
                      </td>
                      {row.cells.map((cell) => (
                        <td
                          key={`${key}-${cell.bid_id}`}
                          className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums"
                        >
                          <div className="flex items-center justify-end gap-1.5">
                            <span className={cellColorClass(cell.leveled_total, m)}>
                              {cell.leveled_total > 0
                                ? formatNumber(cell.leveled_total)
                                : '-'}
                            </span>
                            {statusBadge(cell.status, t)}
                          </div>
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-border bg-surface-secondary/30">
                  <td className="px-3 py-3 font-bold text-content-primary sticky left-0 bg-surface-secondary">
                    {t('tendering.leveling.total_leveled', 'TOTAL LEVELED')}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-right font-bold tabular-nums text-content-primary">
                    {/* Reference total */}
                    {formatCurrency(
                      matrix.rows.reduce(
                        (s, r) => s + r.reference_total, 0,
                      ),
                      matrixCurrency,
                    )}
                  </td>
                  {matrix.bid_summaries.map((bs) => (
                    <td
                      key={`total-${bs.bid_id}`}
                      className="whitespace-nowrap px-3 py-3 text-right font-bold tabular-nums text-content-primary"
                    >
                      {formatCurrency(
                        Number(bs.leveled_amount),
                        bs.currency || matrixCurrency,
                      )}
                    </td>
                  ))}
                </tr>
              </tfoot>
            </table>
          </div>
        </>
      )}
    </Card>
  );
}
