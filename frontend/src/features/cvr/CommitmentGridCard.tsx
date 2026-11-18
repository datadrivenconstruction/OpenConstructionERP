/**
 * Commitment grid: per priced bill line, the cost budget (target rate, else
 * unit rate), what orders and subcontracts have committed, what remains to buy
 * and what has been received. Figures come straight from the API.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { Card, EmptyState, RecoveryCard, SkeletonTable, Badge } from '@/shared/ui';
import { fmtNumber } from '@/shared/lib/formatters';
import { formatCurrency, toNum } from '@/shared/lib/money';
import { fetchCommitmentGrid } from './api';
import { CommercialFindings } from './CommercialFindings';

function qty(value: string): string {
  const n = toNum(value);
  return Number.isFinite(n) ? fmtNumber(n, 3) : value;
}

export function CommitmentGridCard({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['commitment-grid', projectId],
    queryFn: () => fetchCommitmentGrid(projectId),
    enabled: open && !!projectId,
  });
  const currency = data?.currency ?? '';

  return (
    <Card padding="md">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 text-left"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span>
          <span className="oe-card-title">{t('commercial_control.grid_title', { defaultValue: 'Commitments by bill line' })}</span>
          <span className="ml-2 text-xs text-content-tertiary">
            {t('commercial_control.grid_hint', {
              defaultValue: 'Budget at target cost against orders and subcontracts, what remains to buy and what has been received',
            })}
          </span>
        </span>
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </button>
      {open && (
        <div className="mt-3 space-y-3">
          {isLoading ? (
            <SkeletonTable rows={4} columns={8} />
          ) : isError ? (
            <RecoveryCard error={error} onRetry={() => refetch()} />
          ) : !data || data.rows.length === 0 ? (
            <EmptyState
              title={t('commercial_control.grid_empty', { defaultValue: 'No priced bill lines yet' })}
              description={t('commercial_control.grid_empty_desc', {
                defaultValue: 'Price the bill of quantities to see budget, commitments and what remains per line.',
              })}
            />
          ) : (
            <>
              <CommercialFindings findings={data.findings} />
              <div className="overflow-x-auto">
                <table className="oe-table w-full min-w-[960px]">
                  <thead>
                    <tr className="text-left text-2xs">
                      <th className="pr-3">{t('commercial_control.col_line', { defaultValue: 'Line' })}</th>
                      <th className="pr-3 text-right">{t('commercial_control.col_budget_qty', { defaultValue: 'Budget qty' })}</th>
                      <th className="pr-3 text-right">{t('commercial_control.col_budget', { defaultValue: 'Budget' })}</th>
                      <th className="pr-3 text-right">{t('commercial_control.col_committed_qty', { defaultValue: 'Committed qty' })}</th>
                      <th className="pr-3 text-right">{t('commercial_control.col_committed', { defaultValue: 'Committed' })}</th>
                      <th className="pr-3 text-right">{t('commercial_control.col_remaining_qty', { defaultValue: 'Remaining qty' })}</th>
                      <th className="pr-3 text-right">{t('commercial_control.col_remaining', { defaultValue: 'Remaining' })}</th>
                      <th className="pr-3 text-right">{t('commercial_control.col_received_qty', { defaultValue: 'Received qty' })}</th>
                      <th className="pr-3 text-right">{t('commercial_control.col_received', { defaultValue: 'Received' })}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows.map((row) => {
                      const over = row.over_committed_qty || row.over_committed_value;
                      return (
                        <tr key={row.boq_position_id}>
                          <td className="pr-3">
                            <div className="flex items-center gap-1.5">
                              <span className="font-medium">{row.ordinal || '-'}</span>
                              <span className="max-w-[18rem] truncate text-content-secondary" title={row.description}>
                                {row.description}
                              </span>
                              {row.budget_basis === 'unit_rate' && (
                                <Badge variant="neutral">{t('commercial_control.basis_unit_rate', { defaultValue: 'no target' })}</Badge>
                              )}
                              {!row.on_cost_spine && (
                                <Badge variant="neutral">{t('commercial_control.off_spine', { defaultValue: 'no cost line' })}</Badge>
                              )}
                            </div>
                          </td>
                          <td className="pr-3 text-right tabular-nums">{qty(row.budget_qty)} {row.unit}</td>
                          <td className="pr-3 text-right tabular-nums">{formatCurrency(row.budget_value, currency)}</td>
                          <td className={'pr-3 text-right tabular-nums ' + (row.over_committed_qty ? 'text-semantic-error' : '')}>
                            {qty(row.committed_qty)}
                          </td>
                          <td className={'pr-3 text-right tabular-nums ' + (row.over_committed_value ? 'text-semantic-error' : '')}>
                            {formatCurrency(row.committed_value, currency)}
                          </td>
                          <td className={'pr-3 text-right tabular-nums ' + (over ? 'text-semantic-error' : 'text-content-secondary')}>
                            {qty(row.remaining_qty)}
                          </td>
                          <td className={'pr-3 text-right tabular-nums ' + (over ? 'text-semantic-error' : 'text-content-secondary')}>
                            {formatCurrency(row.remaining_value, currency)}
                          </td>
                          <td className="pr-3 text-right tabular-nums text-content-tertiary">{qty(row.received_qty)}</td>
                          <td className="pr-3 text-right tabular-nums text-content-tertiary">{formatCurrency(row.received_value, currency)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td className="pr-3" colSpan={2}>{t('cvr.totals', { defaultValue: 'Totals' })}</td>
                      <td className="pr-3 text-right tabular-nums">{formatCurrency(data.totals.budget_value ?? '0', currency)}</td>
                      <td />
                      <td className="pr-3 text-right tabular-nums">{formatCurrency(data.totals.committed_value ?? '0', currency)}</td>
                      <td />
                      <td className="pr-3 text-right tabular-nums">{formatCurrency(data.totals.remaining_value ?? '0', currency)}</td>
                      <td />
                      <td className="pr-3 text-right tabular-nums">{formatCurrency(data.totals.received_value ?? '0', currency)}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </Card>
  );
}
