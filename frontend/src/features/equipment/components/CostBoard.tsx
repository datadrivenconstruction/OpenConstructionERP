// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Cost board of the Telematics tab: owning against operating cost per machine,
 * set against used and billed hours, with a keep, rent or return suggestion.
 */
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Card, CardContent, CardHeader, EmptyState, ErrorState } from '@/shared/ui';
import { RuleResultsList } from '@/shared/ui/RuleResultsList';
import { fmtNumber } from '@/shared/lib/formatters';
import { currencyFractionDigits } from '@/shared/lib/money';
import { getErrorMessage } from '@/shared/lib/api';
import { fetchCostBoard } from '../telematicsApi';
import { lastDaysWindow, moneyWithCurrency, suggestionTone } from '../telematicsFormat';

const WINDOW_DAYS = 14;

export function CostBoard() {
  const { t } = useTranslation();
  const win = useMemo(() => lastDaysWindow(WINDOW_DAYS), []);
  const q = useQuery({
    queryKey: ['equipment', 'telematics', 'cost-board', win.date_from, win.date_to],
    queryFn: () => fetchCostBoard(win.date_from, win.date_to),
  });
  const machines = q.data?.machines ?? [];
  const totals = Object.entries(q.data?.totals_by_currency ?? {});
  const th = 'px-2 py-2 text-right font-medium';
  const num = 'px-2 py-2 text-right tabular-nums';
  const dash = '-';

  return (
    <Card>
      <CardHeader
        title={t('equipment.costboard.title', { defaultValue: 'Cost board, last 14 days' })}
        subtitle={t('equipment.costboard.subtitle', {
          defaultValue:
            'Owning against operating cost per machine, set against used and billed hours, with a keep, rent or return suggestion.',
        })}
      />
      <CardContent>
        {q.isError ? (
          <ErrorState
            title={t('equipment.costboard.failed', { defaultValue: 'Could not load the cost board' })}
            hint={getErrorMessage(q.error)}
            onRetry={() => q.refetch()}
          />
        ) : q.isLoading ? (
          <p className="py-8 text-center text-sm text-content-tertiary">
            {t('common.loading', { defaultValue: 'Loading...' })}
          </p>
        ) : machines.length === 0 ? (
          <EmptyState
            title={t('equipment.costboard.empty_title', { defaultValue: 'No machines on the board' })}
            description={t('equipment.costboard.empty_hint', {
              defaultValue: 'Add equipment to the fleet; telematics hours fill in the used time.',
            })}
          />
        ) : (
          <div className="space-y-4">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[980px] text-sm">
                <thead>
                  <tr className="border-b border-border-light text-xs uppercase tracking-wide text-content-tertiary">
                    <th className="py-2 pr-3 text-left font-medium">
                      {t('equipment.costboard.col_machine', { defaultValue: 'Machine' })}
                    </th>
                    <th className={th}>{t('equipment.costboard.col_owning', { defaultValue: 'Owning' })}</th>
                    <th className={th}>{t('equipment.costboard.col_operating', { defaultValue: 'Operating' })}</th>
                    <th className={th}>{t('equipment.costboard.col_total', { defaultValue: 'Total' })}</th>
                    <th className={th}>{t('equipment.costboard.col_used', { defaultValue: 'Used h' })}</th>
                    <th className={th}>{t('equipment.costboard.col_billed', { defaultValue: 'Billed h' })}</th>
                    <th className={th}>{t('equipment.costboard.col_idle', { defaultValue: 'Idle %' })}</th>
                    <th className={th}>{t('equipment.costboard.col_per_hour', { defaultValue: 'Cost per used h' })}</th>
                    <th className={th}>{t('equipment.costboard.col_market', { defaultValue: 'Market per h' })}</th>
                    <th className={th}>{t('equipment.costboard.col_recovery', { defaultValue: 'Recovered' })}</th>
                    <th className="py-2 pl-3 text-left font-medium">
                      {t('equipment.costboard.col_suggestion', { defaultValue: 'Suggestion' })}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {machines.map((m) => (
                    <tr key={m.equipment_id} className="border-b border-border-light last:border-0">
                      <td className="py-2 pr-3">
                        <div className="font-medium text-content-primary">{m.code}</div>
                        <div className="text-xs text-content-tertiary">{m.name}</div>
                      </td>
                      <td className={num}>{fmtNumber(m.owning_cost, currencyFractionDigits(m.currency))}</td>
                      <td className={num}>{fmtNumber(m.operating_cost, currencyFractionDigits(m.currency))}</td>
                      <td className={`${num} font-medium`}>
                        {moneyWithCurrency(fmtNumber(m.total_cost, currencyFractionDigits(m.currency)), m.currency)}
                      </td>
                      <td className={num}>{fmtNumber(m.used_hours, 1)}</td>
                      <td className={num}>{fmtNumber(m.billed_hours, 1)}</td>
                      <td className={num}>{m.idle_pct == null ? dash : `${fmtNumber(m.idle_pct, 1)}%`}</td>
                      <td className={num}>{m.cost_per_used_hour == null ? dash : fmtNumber(m.cost_per_used_hour, currencyFractionDigits(m.currency))}</td>
                      <td className={num}>{m.market_hour_rate == null ? dash : fmtNumber(m.market_hour_rate, currencyFractionDigits(m.currency))}</td>
                      <td className={num}>{m.recovery_pct == null ? dash : `${fmtNumber(m.recovery_pct, 0)}%`}</td>
                      <td className="py-2 pl-3">
                        <span
                          className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${suggestionTone(m.suggestion)}`}
                        >
                          {t(`equipment.costboard.suggestion.${m.suggestion}`, { defaultValue: m.suggestion })}
                        </span>
                        <div className="mt-0.5 max-w-[260px] text-xs text-content-tertiary">
                          {t(`equipment.costboard.reason.${m.reason}`, { defaultValue: m.reason })}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
                {totals.length > 0 && (
                  <tfoot>
                    {totals.map(([cur, tot]) => (
                      <tr key={cur} className="border-t-2 border-border-light font-semibold">
                        <td className="py-2 pr-3">
                          {t('equipment.costboard.totals', { defaultValue: 'Total' })} {cur}
                        </td>
                        <td className={num}>{fmtNumber(tot.owning_cost, currencyFractionDigits(cur))}</td>
                        <td className={num}>{fmtNumber(tot.operating_cost, currencyFractionDigits(cur))}</td>
                        <td className={num}>{fmtNumber(tot.total_cost, currencyFractionDigits(cur))}</td>
                        <td colSpan={7} />
                      </tr>
                    ))}
                  </tfoot>
                )}
              </table>
            </div>
            <RuleResultsList results={q.data?.results ?? []} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
