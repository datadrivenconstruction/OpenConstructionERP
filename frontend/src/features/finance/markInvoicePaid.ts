// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { apiGet, apiPost } from '@/shared/lib/api';

/** The slice of an invoice that settling it needs (InvoiceResponse on the wire). */
export interface SettleableInvoice {
  id: string;
  amount_total?: string | number | null;
  amount?: string | number | null;
  retention_amount?: string | number | null;
  currency_code?: string | null;
}

interface PaymentRow {
  amount: string;
  withholding_amount?: string | null;
  is_refund?: boolean;
}

function num(value: unknown): number {
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? n : 0;
}

function cents(value: number): number {
  return Math.round(value * 100) / 100;
}

/**
 * What is still to be settled on an invoice, split into cash and retainage.
 *
 * A payment row carries the cash paid and the retainage withheld beside it,
 * and both reduce what is still owed. The retainage still to hold back is the
 * invoice's own retention less what earlier payments already withheld, and it
 * never exceeds what is left.
 */
export function remainingSettlement(
  invoice: SettleableInvoice,
  payments: PaymentRow[],
): { gross: number; cash: number; withheld: number } {
  const total = num(invoice.amount_total ?? invoice.amount);
  let settled = 0;
  let withheldBefore = 0;
  for (const p of payments) {
    const sign = p.is_refund ? -1 : 1;
    settled += sign * (num(p.amount) + num(p.withholding_amount));
    if (!p.is_refund) withheldBefore += num(p.withholding_amount);
  }
  const gross = cents(Math.max(0, total - settled));
  const withheld = cents(Math.min(gross, Math.max(0, num(invoice.retention_amount) - withheldBefore)));
  return { gross, cash: cents(gross - withheld), withheld };
}

/**
 * Mark an invoice paid the way the ledger needs it: record the payment for
 * what is still open, then move the status.
 *
 * `/pay/` alone only changes the status. No payment row was written, so the
 * payments list, the cash flow and the statements stayed at zero for every
 * invoice closed with the row button. The payment goes through
 * `record-payment` (which holds back retainage), keyed on the invoice so a
 * second click, or a retry after `/pay/` failed, returns the payment already
 * made instead of paying twice. An invoice already settled in full by earlier
 * payments records nothing more.
 */
export async function settleAndMarkPaid(invoice: SettleableInvoice, paymentDate: string): Promise<void> {
  const page = await apiGet<{ items?: PaymentRow[] }>(
    `/v1/finance/payments/?invoice_id=${encodeURIComponent(invoice.id)}&limit=100`,
  );
  const { gross, cash, withheld } = remainingSettlement(invoice, page?.items ?? []);
  if (gross > 0) {
    await apiPost(`/v1/finance/invoices/${encodeURIComponent(invoice.id)}/record-payment/`, {
      payment_date: paymentDate,
      amount: cash.toFixed(2),
      withholding_amount: withheld.toFixed(2),
      currency_code: invoice.currency_code || '',
      idempotency_key: `markpaid:${invoice.id}`,
    });
  }
  await apiPost(`/v1/finance/${encodeURIComponent(invoice.id)}/pay/`);
}
