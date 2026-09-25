// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ClaimInvoicePreview — Gap E (Wave 6).
 *
 * Shows the accounts-receivable invoice that a certified progress claim
 * spawns, with the retainage explicitly broken out (gross / retained / net
 * collectible). Lets a manager raise the receivable from the claim with one
 * click; the backend endpoint is idempotent, so a second click (or an
 * already-auto-created invoice from the certification event) simply re-shows
 * the existing invoice rather than duplicating it.
 *
 * Self-contained: drops into the contracts claim detail panel or the finance
 * page without touching either's large component. It only needs the claim id.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Button, Badge, Card, CardContent, CardHeader } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { apiGet, apiPost, getErrorMessage } from '@/shared/lib/api';

interface ClaimInvoiceLineItem {
  id: string;
  description: string;
  amount: string;
}

interface ClaimInvoice {
  id: string;
  invoice_number: string;
  status: string;
  currency_code: string;
  amount_subtotal: string;
  retention_amount: string;
  amount_total: string;
  invoice_direction?: string;
  source_claim_id: string | null;
  line_items?: ClaimInvoiceLineItem[];
}

export type ClaimInvoiceDirection = 'receivable' | 'payable';

export interface ClaimInvoicePreviewProps {
  /** The certified progress claim to preview / invoice. */
  claimId: string;
  /** Whether the current claim is in `certified` status (gates the action). */
  certified?: boolean;
  /**
   * Which way the claim is billed before an invoice exists: a client claim is
   * a receivable, a subcontractor's claim is a payable. The invoice's own
   * direction wins once it exists.
   */
  direction?: ClaimInvoiceDirection;
  /** Called with the resulting invoice id after a successful raise. */
  onInvoiced?: (invoiceId: string) => void;
}

/** How often to look again for the invoice the certification raises. */
const AWAIT_INVOICE_MS = 3000;

export function ClaimInvoicePreview({
  claimId,
  certified = true,
  direction = 'receivable',
  onInvoiced,
}: ClaimInvoicePreviewProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  // Does an invoice already exist for this claim? 404 => not yet. The
  // certification raises it after its own request commits, so a page that
  // asked while the claim was still approved kept "Not raised" in the cache.
  // The status is part of the key, and a certified claim with no invoice yet
  // keeps asking until the invoice lands.
  const { data: existing, isLoading } = useQuery<ClaimInvoice | null>({
    queryKey: ['finance', 'claim-receivable', claimId, certified],
    queryFn: async () => {
      try {
        return await apiGet<ClaimInvoice>(
          `/api/v1/finance/claims/${encodeURIComponent(claimId)}/receivable-invoice/`,
        );
      } catch {
        return null;
      }
    },
    staleTime: 0,
    refetchInterval: (query) => (certified && !query.state.data ? AWAIT_INVOICE_MS : false),
  });

  const raise = useMutation({
    mutationFn: async () => {
      return apiPost<ClaimInvoice>('/api/v1/finance/invoices/from-claim/', {
        claim_id: claimId,
      });
    },
    onSuccess: (inv) => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ['finance', 'claim-receivable', claimId] });
      queryClient.invalidateQueries({ queryKey: ['finance', 'invoices'] });
      onInvoiced?.(inv.id);
    },
    onError: (e: unknown) => {
      setError(getErrorMessage(e));
    },
  });

  const invoice = existing ?? null;
  const currency = invoice?.currency_code || '';
  const payable = (invoice?.invoice_direction ?? direction) === 'payable';
  // The invoice stores the gross in its subtotal and holds retention beside
  // it, so what changes hands now is the total less the retention.
  const netNow = invoice
    ? String(Math.round((Number(invoice.amount_total) - Number(invoice.retention_amount)) * 100) / 100)
    : '0';

  return (
    <Card>
      <CardHeader
        title={payable ? t('finance.claimInvoice.titlePayable') : t('finance.claimInvoice.title')}
        action={
          invoice ? (
            <Badge variant="success">{t('finance.claimInvoice.raised')}</Badge>
          ) : (
            <Badge variant="neutral">{t('finance.claimInvoice.notRaised')}</Badge>
          )
        }
      />
      <CardContent>
        {isLoading ? (
          <p className="text-xs text-[var(--text-secondary)]">{t('common.loading')}</p>
        ) : invoice ? (
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-[var(--text-secondary)]">
                {t('finance.claimInvoice.invoiceNumber')}
              </dt>
              <dd className="font-medium">{invoice.invoice_number}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-[var(--text-secondary)]">
                {t('finance.claimInvoice.gross')}
              </dt>
              <dd>
                <MoneyDisplay amount={invoice.amount_total} currency={currency} />
              </dd>
            </div>
            <div className="flex justify-between text-[var(--accent)]">
              <dt>{t('finance.claimInvoice.retained')}</dt>
              <dd>
                <MoneyDisplay amount={invoice.retention_amount} currency={currency} />
              </dd>
            </div>
            <div className="flex justify-between border-t border-[var(--border)] pt-2 font-semibold">
              <dt>
                {payable
                  ? t('finance.claimInvoice.netPayable')
                  : t('finance.claimInvoice.netCollectible')}
              </dt>
              <dd>
                <MoneyDisplay amount={netNow} currency={currency} />
              </dd>
            </div>
          </dl>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-[var(--text-secondary)]">
              {certified
                ? payable
                  ? t('finance.claimInvoice.readyHintPayable')
                  : t('finance.claimInvoice.readyHint')
                : payable
                  ? t('finance.claimInvoice.notCertifiedHintPayable')
                  : t('finance.claimInvoice.notCertifiedHint')}
            </p>
            <Button
              size="sm"
              onClick={() => raise.mutate()}
              disabled={!certified || raise.isPending}
            >
              {raise.isPending
                ? t('finance.claimInvoice.raising')
                : payable
                  ? t('finance.claimInvoice.raiseActionPayable')
                  : t('finance.claimInvoice.raiseAction')}
            </Button>
          </div>
        )}
        {error && <p className="mt-2 text-xs text-[var(--error)]">{error}</p>}
      </CardContent>
    </Card>
  );
}

export default ClaimInvoicePreview;
