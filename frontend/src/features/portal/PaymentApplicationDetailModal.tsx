// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Read-only detail modal for one of the subcontractor's payment applications.
 * Shows the work-package lines (claimed / certified / approved) and the
 * gross / retention / net summary, all in the application's own currency.
 */

import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { X, Loader2, AlertCircle } from 'lucide-react';
import { Badge } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { getMyPaymentApplication } from './api';

const STATUS_VARIANT: Record<string, 'neutral' | 'blue' | 'warning' | 'success' | 'error'> = {
  submitted: 'blue',
  foreman_approved: 'warning',
  finance_approved: 'success',
  paid: 'success',
  rejected: 'error',
};

function money(amount: string, currency: string): string {
  return currency ? `${currency} ${amount}` : amount;
}

export function PaymentApplicationDetailModal({
  id,
  onClose,
}: {
  id: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['portal', 'payment-application', id],
    queryFn: () => getMyPaymentApplication(id),
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const pa = q.data;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('payportal.detail_title', { defaultValue: 'Application detail' })}
        className="relative max-h-[90dvh] w-full max-w-lg overflow-y-auto rounded-t-2xl bg-surface-elevated shadow-xl sm:rounded-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border-light bg-surface-elevated px-5 py-3">
          <h2 className="font-mono text-sm font-semibold text-content-primary">
            {pa?.application_number ?? t('payportal.detail_title', { defaultValue: 'Application detail' })}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 hover:bg-surface-secondary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        <div className="space-y-4 p-5">
          {q.isLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="animate-spin text-oe-blue" size={24} />
            </div>
          ) : q.error || !pa ? (
            <div className="flex flex-col items-center gap-2 py-8 text-center">
              <AlertCircle size={22} className="text-content-tertiary" />
              <p className="text-sm text-content-secondary">
                {q.error instanceof Error
                  ? q.error.message
                  : t('payportal.load_failed', { defaultValue: 'Could not load' })}
              </p>
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between">
                <span className="text-sm text-content-secondary">
                  {pa.period_start ? <DateDisplay value={pa.period_start} /> : '—'}
                  {pa.period_end ? (
                    <>
                      {' – '}
                      <DateDisplay value={pa.period_end} />
                    </>
                  ) : null}
                </span>
                <Badge variant={STATUS_VARIANT[pa.status] ?? 'neutral'} dot>
                  {t(`payportal.status_${pa.status}`, { defaultValue: pa.status })}
                </Badge>
              </div>

              <div>
                <p className="mb-2 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
                  {t('payportal.lines_detail', { defaultValue: 'Work package lines' })}
                </p>
                <div className="overflow-x-auto rounded-lg border border-border-light">
                  <table className="w-full text-sm">
                    <thead className="bg-surface-secondary text-2xs uppercase tracking-wide text-content-tertiary">
                      <tr>
                        <th className="px-3 py-2 text-left">
                          {t('payportal.work_package', { defaultValue: 'Work package' })}
                        </th>
                        <th className="px-3 py-2 text-right">
                          {t('payportal.claimed', { defaultValue: 'Claimed' })}
                        </th>
                        <th className="px-3 py-2 text-right">
                          {t('payportal.certified', { defaultValue: 'Certified' })}
                        </th>
                        <th className="px-3 py-2 text-right">
                          {t('payportal.approved', { defaultValue: 'Approved' })}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {pa.lines.map((l) => (
                        <tr key={l.work_package_id} className="border-t border-border-light">
                          <td className="px-3 py-2 text-content-primary">{l.work_package_name}</td>
                          <td className="px-3 py-2 text-right text-content-secondary">
                            {l.claimed_amount}
                          </td>
                          <td className="px-3 py-2 text-right text-content-secondary">
                            {l.certified_amount}
                          </td>
                          <td className="px-3 py-2 text-right text-content-secondary">
                            {l.approved_amount}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="space-y-1 border-t border-border-light pt-3">
                <Row
                  label={t('payportal.gross', { defaultValue: 'Gross' })}
                  value={money(pa.gross_amount, pa.currency)}
                />
                <Row
                  label={t('payportal.retention', { defaultValue: 'Retention' })}
                  value={`- ${money(pa.retention_amount, pa.currency)}`}
                />
                <Row
                  strong
                  label={t('payportal.net', { defaultValue: 'Net' })}
                  value={money(pa.net_amount, pa.currency)}
                />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className={strong ? 'font-semibold text-content-primary' : 'text-content-secondary'}>
        {label}
      </span>
      <span className={strong ? 'font-semibold text-content-primary' : 'text-content-primary'}>
        {value}
      </span>
    </div>
  );
}
