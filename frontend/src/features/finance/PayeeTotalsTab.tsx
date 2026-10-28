// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Building2, Download, Lock, ReceiptText } from 'lucide-react';
import clsx from 'clsx';
import { Badge, Button, Card, EmptyState, RecoveryCard, SkeletonTable } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { ApiError } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { legalEntitiesApi } from '@/features/legal-entities/api';
import { downloadPayeeTotalsCsv, getPayeeTotals, type PayeeTotalsQuery } from './api';

const inputCls =
  'h-10 rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/** The previous calendar year, the period most payee returns cover. */
function lastYear(): { from: string; to: string } {
  const year = new Date().getFullYear() - 1;
  return { from: `${year}-01-01`, to: `${year}-12-31` };
}

/**
 * Supplier payments of one legal entity over a period, for an annual payee
 * return such as Canada's T5018. The server adds the payments up per payee
 * and currency, names the return of the entity's country with its threshold
 * and due date, and marks the payees below the threshold.
 */
export function PayeeTotalsTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [entityId, setEntityId] = useState<string | null>(null);
  const [period, setPeriod] = useState(lastYear);
  const [showAll, setShowAll] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const entitiesQ = useQuery({
    queryKey: ['legal-entities', 'list', 'payee-totals'],
    queryFn: () => legalEntitiesApi.list(false),
    staleTime: 5 * 60_000,
  });
  const projectEntityQ = useQuery({
    queryKey: ['legal-entities', 'project', projectId],
    queryFn: () => legalEntitiesApi.projectEntity(projectId),
    staleTime: 5 * 60_000,
  });
  const entities = entitiesQ.data?.items ?? [];
  const effectiveEntityId = entityId ?? projectEntityQ.data?.legal_entity?.id ?? entities[0]?.id ?? '';

  const query: PayeeTotalsQuery = { legalEntityId: effectiveEntityId, dateFrom: period.from, dateTo: period.to };
  const validPeriod = !!period.from && !!period.to && period.from <= period.to;
  const totalsQ = useQuery({
    queryKey: ['finance', 'payee-totals', query],
    queryFn: () => getPayeeTotals(query),
    enabled: !!effectiveEntityId && validPeriod,
  });
  const report = totalsQ.data;
  const ret = report?.payee_return ?? null;
  const rows = (report?.items ?? []).filter((row) => showAll || !row.below_threshold);
  const hidden = (report?.items.length ?? 0) - rows.length;

  const download = async () => {
    if (!report) return;
    setDownloading(true);
    try {
      const form = ret?.form ?? 'payees';
      await downloadPayeeTotalsCsv(query, `${form}_${period.from}_${period.to}.csv`);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('finance.payee_download_failed', { defaultValue: 'The payee totals could not be downloaded' }),
        message: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setDownloading(false);
    }
  };

  const noEntities = entitiesQ.isSuccess && entities.length === 0;

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-oe-blue/15 bg-oe-blue/[0.03] p-3">
        <p className="text-sm text-content-secondary">
          {t('finance.payee_subtitle', {
            defaultValue:
              'What one company paid each supplier over a period, for the yearly return some countries require, such as the T5018 in Canada. Payments count on the day they were made, refunds are taken off, and retention counts when it is paid out.',
          })}
        </p>
      </div>

      {noEntities ? (
        <EmptyState
          icon={<Building2 size={26} strokeWidth={1.5} />}
          title={t('finance.payee_no_entities_title', { defaultValue: 'No legal entity yet' })}
          description={t('finance.payee_no_entities_desc', {
            defaultValue:
              'Payee totals are worked out per company. Add your legal entities and assign projects to them first.',
          })}
        />
      ) : (
        <>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
                {t('finance.ageing_entity', { defaultValue: 'Legal entity' })}
              </span>
              <select
                value={effectiveEntityId}
                onChange={(e) => setEntityId(e.target.value)}
                className={clsx(inputCls, 'max-w-[16rem]')}
              >
                {entities.map((entity) => (
                  <option key={entity.id} value={entity.id}>
                    {entity.code ? `${entity.code} · ${entity.name}` : entity.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
                {t('finance.statement_date_from', { defaultValue: 'From' })}
              </span>
              <input
                type="date"
                value={period.from}
                onChange={(e) => setPeriod((p) => ({ ...p, from: e.target.value }))}
                className={inputCls}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
                {t('finance.statement_date_to', { defaultValue: 'To' })}
              </span>
              <input
                type="date"
                value={period.to}
                onChange={(e) => setPeriod((p) => ({ ...p, to: e.target.value }))}
                className={inputCls}
              />
            </label>
            <Button
              variant="secondary"
              icon={<Download size={14} />}
              onClick={download}
              loading={downloading}
              disabled={!report || report.items.length === 0}
            >
              {t('finance.statement_download_csv', { defaultValue: 'Download CSV' })}
            </Button>
          </div>

          {!validPeriod ? (
            <p className="text-sm text-semantic-error">
              {t('finance.payee_bad_period', { defaultValue: 'The period has to start on or before the day it ends.' })}
            </p>
          ) : totalsQ.isError && totalsQ.error instanceof ApiError && totalsQ.error.status === 403 ? (
            <EmptyState
              icon={<Lock size={26} strokeWidth={1.5} />}
              title={t('finance.retention_forbidden_title', { defaultValue: 'Finance access required' })}
              description={t('finance.payee_forbidden_desc', {
                defaultValue:
                  'You do not have permission to read finance data, so supplier payments cannot be shown. Ask an administrator to grant the finance read role.',
              })}
            />
          ) : totalsQ.isError ? (
            <RecoveryCard error={totalsQ.error} onRetry={() => totalsQ.refetch()} />
          ) : !report ? (
            <SkeletonTable rows={6} columns={6} />
          ) : (
            <>
              {ret && (
                <Card padding="none" className="space-y-1 p-4" data-testid="payee-return">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="blue" size="sm">
                      {ret.form}
                    </Badge>
                    <span className="text-sm font-medium text-content-primary">{ret.name}</span>
                  </div>
                  <p className="flex flex-wrap items-center gap-1 text-xs text-content-secondary">
                    <span>{t('finance.payee_due_on', { defaultValue: 'Due by' })}</span>
                    <DateDisplay value={ret.due_on} className="font-medium text-content-primary" />
                    <span>·</span>
                    <span>{t('finance.payee_threshold', { defaultValue: 'Payees paid at least' })}</span>
                    <MoneyDisplay amount={ret.threshold} currency={ret.currency} />
                  </p>
                  <p className="text-2xs text-content-tertiary">{ret.reference}</p>
                </Card>
              )}

              {report.missing_tax_id > 0 && (
                <div className="flex items-start gap-2 rounded-lg border border-semantic-warning/30 bg-semantic-warning-bg p-3 text-sm text-content-primary">
                  <AlertTriangle size={16} className="mt-0.5 shrink-0 text-semantic-warning" />
                  <span>
                    {t('finance.payee_missing_tax_id', {
                      defaultValue:
                        'Payees without a tax or business number on their contact: {{n}}. The return needs it, so add it to the contact before filing.',
                      n: report.missing_tax_id,
                    })}
                  </span>
                </div>
              )}

              {report.items.length === 0 ? (
                <EmptyState
                  icon={<ReceiptText size={26} strokeWidth={1.5} />}
                  title={t('finance.payee_empty_title', { defaultValue: 'No supplier payments' })}
                  description={t('finance.payee_empty_desc', {
                    defaultValue: 'This company recorded no payment to a supplier in the period.',
                  })}
                />
              ) : (
                <Card padding="none" className="overflow-hidden">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-content-secondary">
                          <th className="px-4 py-3 font-medium">
                            {t('finance.payee_col_payee', { defaultValue: 'Payee' })}
                          </th>
                          <th className="px-3 py-3 font-medium">
                            {t('finance.payee_col_tax_id', { defaultValue: 'Tax or business number' })}
                          </th>
                          <th className="px-3 py-3 text-right font-medium">
                            {t('finance.payee_col_payments', { defaultValue: 'Payments' })}
                          </th>
                          <th className="px-3 py-3 text-right font-medium">
                            {t('finance.payee_col_total', { defaultValue: 'Paid in period' })}
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((row) => (
                          <tr
                            key={`${row.contact_id ?? 'none'}-${row.currency_code}`}
                            className={clsx('border-b border-border/60', row.below_threshold && 'opacity-60')}
                          >
                            <td className="px-4 py-2.5">
                              <span className="text-content-primary">
                                {row.payee_name ||
                                  t('finance.retention_unnamed', { defaultValue: 'Unspecified counterparty' })}
                              </span>
                              {row.payee_address && (
                                <span className="block text-2xs text-content-tertiary">{row.payee_address}</span>
                              )}
                              {row.below_threshold && (
                                <span className="mt-0.5 block text-2xs text-content-tertiary">
                                  {t('finance.payee_below_threshold', { defaultValue: 'Below the threshold' })}
                                </span>
                              )}
                            </td>
                            <td className="px-3 py-2.5 font-mono text-xs">
                              {row.payee_tax_id ? (
                                <span className="text-content-primary">{row.payee_tax_id}</span>
                              ) : (
                                <span className="text-semantic-warning">
                                  {t('finance.payee_no_tax_id', { defaultValue: 'missing' })}
                                </span>
                              )}
                            </td>
                            <td className="px-3 py-2.5 text-right tabular-nums text-content-secondary">
                              {row.payment_count}
                            </td>
                            <td className="px-3 py-2.5 text-right font-semibold tabular-nums text-content-primary">
                              <MoneyDisplay amount={row.total} currency={row.currency_code || undefined} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {hidden > 0 || showAll ? (
                    <div className="border-t border-border/60 px-4 py-2">
                      <button
                        type="button"
                        onClick={() => setShowAll((v) => !v)}
                        className="text-xs font-medium text-oe-blue hover:underline"
                      >
                        {showAll
                          ? t('finance.payee_hide_below', { defaultValue: 'Hide payees below the threshold' })
                          : t('finance.payee_show_below', {
                              defaultValue: 'Show payees below the threshold ({{n}})',
                              n: hidden,
                            })}
                      </button>
                    </div>
                  ) : null}
                </Card>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
