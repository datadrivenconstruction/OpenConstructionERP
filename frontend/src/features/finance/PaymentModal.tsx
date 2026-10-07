// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * PaymentModal — Gap E (Wave 6) retainage-aware payment recorder.
 *
 * Records a payment against a receivable invoice while holding back retainage.
 * Shows a live breakdown (gross settled / retainage withheld / cash paid) so
 * the user sees exactly what leaves the bank vs what is retained until the
 * release date. Posts to the withholding-aware endpoint
 * `POST /invoices/{id}/record-payment/`, which is idempotent on the supplied
 * idempotency key. Self-contained modal — no edits to the large FinancePage.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { WideModal, WideModalSection, WideModalField } from '@/shared/ui/WideModal';
import { Button, Input } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { apiPost, getErrorMessage } from '@/shared/lib/api';
import { invalidateFinanceFigures } from './financeQueryKeys';
import { subtractDecimalStrings } from '@/shared/lib/exactDecimal';
import { paymentDecimalInput, paymentIdempotencyKey } from './paymentDecimalInput';

export interface PaymentModalProps {
  open: boolean;
  onClose: () => void;
  invoiceId: string;
  /** Invoice total (gross collectible) — Decimal-as-string. */
  amountTotal: string;
  /** Default retainage to withhold — Decimal-as-string (from invoice.retention_amount). */
  retentionAmount?: string;
  currency: string;
  onPaid?: () => void;
}

function paymentBreakdown(total: string, input: string) {
  const gross = subtractDecimalStrings(total, '0');
  // Clearing the optional holdback field retains the existing zero behavior.
  const normalized = paymentDecimalInput(input);
  const entered = normalized === null ? null : subtractDecimalStrings(normalized, '0');
  if (gross === null || gross.startsWith('-') || entered === null) return null;
  const difference = subtractDecimalStrings(gross, entered)!;
  const withheld = entered.startsWith('-') ? '0' : difference.startsWith('-') ? gross : entered;
  return { gross, withheld, cash: subtractDecimalStrings(gross, withheld)! };
}

export function PaymentModal({
  open,
  onClose,
  invoiceId,
  amountTotal,
  retentionAmount = '0',
  currency,
  onPaid,
}: PaymentModalProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [paymentDate, setPaymentDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [withholding, setWithholding] = useState(retentionAmount);
  const [withholdingBadInput, setWithholdingBadInput] = useState(false);
  const [releaseDate, setReleaseDate] = useState('');
  const [reference, setReference] = useState('');
  const [error, setError] = useState<string | null>(null);

  // Live breakdown: gross = invoice total, cash = gross - withheld (clamped).
  const breakdown = withholdingBadInput ? null : paymentBreakdown(amountTotal, withholding);
  const gross = breakdown?.gross ?? null;
  const withheld = breakdown?.withheld ?? null;
  const cash = breakdown?.cash ?? null;

  const idempotencyKey = useMemo(
    () => `pay-${invoiceId}-${paymentDate}-${withholding}`,
    [invoiceId, paymentDate, withholding],
  );

  const pay = useMutation({
    mutationFn: async () => {
      if (!breakdown) throw new Error(t('common.invalid_form', { defaultValue: 'Invalid form' }));
      let key: string;
      try {
        key = await paymentIdempotencyKey(idempotencyKey);
      } catch {
        throw new Error(t('common.error', { defaultValue: 'Error' }));
      }
      return apiPost(`/api/v1/finance/invoices/${encodeURIComponent(invoiceId)}/record-payment/`, {
        payment_date: paymentDate,
        withholding_amount: breakdown.withheld,
        withholding_release_date: releaseDate || null,
        reference: reference || null,
        idempotency_key: key,
      });
    },
    onSuccess: () => {
      setError(null);
      void invalidateFinanceFigures(queryClient);
      onPaid?.();
      onClose();
    },
    onError: (e: unknown) => {
      setError(getErrorMessage(e));
    },
  });

  if (!open) return null;

  return (
    <WideModal open={open} title={t('finance.payment.recordTitle')} onClose={onClose}>
      <WideModalSection title={t('finance.payment.detailsSection')}>
        <WideModalField label={t('finance.payment.date')}>
          <Input type="date" value={paymentDate} onChange={(e) => setPaymentDate(e.target.value)} />
        </WideModalField>
        <WideModalField label={t('finance.payment.withholding')}>
          <Input
            type="number"
            min="0"
            step="0.01"
            value={withholding}
            onInput={(e) => setWithholdingBadInput(e.currentTarget.validity.badInput)}
            onChange={(e) => {
              setWithholding(e.target.value);
              setWithholdingBadInput(e.target.validity.badInput);
            }}
          />
        </WideModalField>
        <WideModalField label={t('finance.payment.releaseDate')}>
          <Input type="date" value={releaseDate} onChange={(e) => setReleaseDate(e.target.value)} />
        </WideModalField>
        <WideModalField label={t('finance.payment.reference')}>
          <Input value={reference} onChange={(e) => setReference(e.target.value)} />
        </WideModalField>
      </WideModalSection>

      <WideModalSection title={t('finance.payment.breakdownSection')}>
        <dl className="space-y-2 text-sm">
          <div className="flex justify-between">
            <dt className="text-[var(--text-secondary)]">{t('finance.payment.gross')}</dt>
            <dd>
              <MoneyDisplay amount={gross} currency={currency} />
            </dd>
          </div>
          <div className="flex justify-between text-[var(--accent)]">
            <dt>{t('finance.payment.retained')}</dt>
            <dd>
              <MoneyDisplay amount={withheld} currency={currency} />
            </dd>
          </div>
          <div className="flex justify-between border-t border-[var(--border)] pt-2 font-semibold">
            <dt>{t('finance.payment.cashPaid')}</dt>
            <dd>
              <MoneyDisplay amount={cash} currency={currency} />
            </dd>
          </div>
        </dl>
      </WideModalSection>

      {(error || breakdown === null) && <p role="alert" className="px-4 text-xs text-[var(--error)]">
        {error || t('common.invalid_form', { defaultValue: 'Invalid form' })}
      </p>}

      <div className="flex justify-end gap-2 px-4 py-3">
        <Button variant="ghost" onClick={onClose} disabled={pay.isPending}>
          {t('common.cancel')}
        </Button>
        <Button onClick={() => pay.mutate()} disabled={pay.isPending || breakdown === null}>
          {pay.isPending ? t('finance.payment.recording') : t('finance.payment.record')}
        </Button>
      </div>
    </WideModal>
  );
}

export default PaymentModal;
