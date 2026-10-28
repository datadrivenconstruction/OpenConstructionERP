// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useQuery } from '@tanstack/react-query';
import { Download } from 'lucide-react';
import clsx from 'clsx';
import { Button, RecoveryCard, SkeletonTable, WideModal } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useToastStore } from '@/stores/useToastStore';
import {
  downloadAccountStatementCsv,
  getAccountStatement,
  type AccountStatementQuery,
  type AgeingRollup,
} from './api';

const inputCls =
  'h-10 rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

function kindLabel(t: TFunction, kind: string): string {
  if (kind === 'invoice') return t('finance.statement_kind_invoice', { defaultValue: 'Invoice' });
  if (kind === 'payment') return t('finance.statement_kind_payment', { defaultValue: 'Payment' });
  if (kind === 'refund') return t('finance.statement_kind_refund', { defaultValue: 'Refund' });
  return kind;
}

function Money({ value, currency, strong }: { value: string; currency: string; strong?: boolean }) {
  if (Number(value) === 0) return <span className="text-content-tertiary">-</span>;
  return (
    <span className={clsx('tabular-nums', strong && 'font-semibold text-content-primary')}>
      <MoneyDisplay amount={value} currency={currency || undefined} />
    </span>
  );
}

/**
 * Statement of account with one counterparty: every posted invoice and
 * payment over a period with a running balance, the balance brought forward
 * and the balance carried, as sent to a customer at month end or reconciled
 * against a supplier's own statement. Opened from a counterparty line of the
 * ageing report, so it keeps that line's legal entity, currency and direction.
 */
export function StatementOfAccountModal({
  row,
  asOf,
  onClose,
}: {
  row: AgeingRollup;
  asOf?: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState(asOf ?? '');
  const [downloading, setDownloading] = useState(false);

  const query: AccountStatementQuery = {
    contactId: row.contact_id ?? '',
    currency: row.currency_code,
    direction: row.direction === 'payable' ? 'payable' : 'receivable',
    legalEntityId: row.legal_entity_id ?? undefined,
    dateFrom: dateFrom || undefined,
    dateTo: dateTo || undefined,
  };
  const statementQ = useQuery({
    queryKey: ['finance', 'statement-of-account', query],
    queryFn: () => getAccountStatement(query),
    enabled: !!row.contact_id,
  });
  const st = statementQ.data;
  const currency = row.currency_code;
  const name = row.counterparty_name || t('finance.retention_unnamed', { defaultValue: 'Unspecified counterparty' });

  const download = async () => {
    setDownloading(true);
    try {
      const safe = name.replace(/[^\w.-]+/g, '_').slice(0, 60) || 'statement';
      await downloadAccountStatementCsv(query, `statement_${safe}_${currency}.csv`);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('finance.statement_download_failed', { defaultValue: 'The statement could not be downloaded' }),
        message: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setDownloading(false);
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      size="xl"
      testId="statement-of-account"
      title={t('finance.statement_title', { defaultValue: 'Statement of account' })}
      subtitle={
        <span>
          {name} · {currency}
          {row.legal_entity_name ? ` · ${row.legal_entity_name}` : ''}
        </span>
      }
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t('common.close', { defaultValue: 'Close' })}
          </Button>
          <Button
            variant="primary"
            icon={<Download size={14} />}
            onClick={download}
            loading={downloading}
            disabled={!st}
          >
            {t('finance.statement_download_csv', { defaultValue: 'Download CSV' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-content-secondary">
          {row.direction === 'payable'
            ? t('finance.statement_hint_payable', {
                defaultValue:
                  'Every invoice from this supplier and every payment to them, in date order. The balance is what we owe them, so it can be checked line by line against the statement they send.',
              })
            : t('finance.statement_hint_receivable', {
                defaultValue:
                  'Every invoice to this customer and every payment from them, in date order. The balance is what they owe us, ready to send as their statement.',
              })}
        </p>

        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('finance.statement_date_from', { defaultValue: 'From' })}
            </span>
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className={inputCls} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('finance.statement_date_to', { defaultValue: 'To' })}
            </span>
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className={inputCls} />
          </label>
        </div>

        {statementQ.isError ? (
          <RecoveryCard error={statementQ.error} onRetry={() => statementQ.refetch()} />
        ) : !st ? (
          <SkeletonTable rows={5} columns={6} />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-content-secondary">
                  <th className="px-3 py-2 font-medium">{t('finance.statement_col_date', { defaultValue: 'Date' })}</th>
                  <th className="px-3 py-2 font-medium">{t('finance.statement_col_type', { defaultValue: 'Type' })}</th>
                  <th className="px-3 py-2 font-medium">
                    {t('finance.statement_col_reference', { defaultValue: 'Reference' })}
                  </th>
                  <th className="px-3 py-2 text-right font-medium">
                    {t('finance.statement_col_charge', { defaultValue: 'Charge' })}
                  </th>
                  <th className="px-3 py-2 text-right font-medium">
                    {t('finance.statement_col_credit', { defaultValue: 'Credit' })}
                  </th>
                  <th className="px-3 py-2 text-right font-medium">
                    {t('finance.statement_col_balance', { defaultValue: 'Balance' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-border/60 bg-surface-secondary/40" data-testid="statement-opening">
                  <td className="px-3 py-2 text-content-secondary">
                    {st.date_from ? <DateDisplay value={st.date_from} /> : '-'}
                  </td>
                  <td colSpan={4} className="px-3 py-2 font-medium text-content-secondary">
                    {t('finance.statement_opening', { defaultValue: 'Balance brought forward' })}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <MoneyDisplay amount={st.opening_balance} currency={currency || undefined} />
                  </td>
                </tr>
                {st.lines.length === 0 ? (
                  <tr className="border-b border-border/60">
                    <td colSpan={6} className="px-3 py-4 text-center text-content-tertiary">
                      {t('finance.statement_no_lines', { defaultValue: 'No invoices or payments in this period.' })}
                    </td>
                  </tr>
                ) : (
                  st.lines.map((line, i) => (
                    <tr key={`${line.invoice_id}-${line.kind}-${i}`} className="border-b border-border/60">
                      <td className="px-3 py-2 text-content-secondary">
                        <DateDisplay value={line.entry_date} />
                      </td>
                      <td className="px-3 py-2 text-content-primary">{kindLabel(t, line.kind)}</td>
                      <td className="px-3 py-2 font-mono text-xs text-content-primary">{line.reference}</td>
                      <td className="px-3 py-2 text-right">
                        <Money value={line.charge} currency={currency} />
                      </td>
                      <td className="px-3 py-2 text-right">
                        <Money value={line.credit} currency={currency} />
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-content-primary">
                        <MoneyDisplay amount={line.balance} currency={currency || undefined} />
                      </td>
                    </tr>
                  ))
                )}
                <tr className="bg-surface-secondary/40" data-testid="statement-closing">
                  <td className="px-3 py-2 text-content-secondary">
                    <DateDisplay value={st.date_to} />
                  </td>
                  <td colSpan={2} className="px-3 py-2 font-semibold text-content-primary">
                    {t('finance.statement_closing', { defaultValue: 'Balance carried' })}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Money value={st.total_charged} currency={currency} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Money value={st.total_credited} currency={currency} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Money value={st.closing_balance} currency={currency} strong />
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </div>
    </WideModal>
  );
}
