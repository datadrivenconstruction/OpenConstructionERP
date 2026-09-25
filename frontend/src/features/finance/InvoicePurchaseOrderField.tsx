// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle } from 'lucide-react';
import { apiGet, apiPost, type Page } from '@/shared/lib/api';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';

/** The slice of a purchase order the picker reads (POResponse on the wire). */
export interface LinkableOrder {
  id: string;
  po_number: string;
  status: string;
  currency_code: string;
  amount_subtotal: string;
  invoiced_net?: string;
  invoice_count?: number;
}

interface InvoiceCheckResult {
  results: Array<{
    rule_id: string;
    severity: string;
    passed: boolean;
    message: string;
  }>;
}

// The server refuses a link to an order in either of these states, so the
// picker does not offer them.
const UNLINKABLE_STATUSES = new Set(['draft', 'cancelled']);

/**
 * The optional purchase order a supplier invoice bills.
 *
 * Offered only on a payable invoice, and only the orders of this project
 * placed with the invoice's supplier, which is the same rule the server
 * applies when it saves the link. Beside the choice it shows what the order
 * is worth, what has been invoiced on it so far and what is still open, all
 * net of VAT, and the three-way match warnings for the amount being entered.
 * The warnings never block the save: the person entering the invoice decides.
 */
export function InvoicePurchaseOrderField({
  projectId,
  contactId,
  value,
  onChange,
  amountSubtotal,
  invoiceId,
}: {
  projectId: string;
  contactId: string;
  value: string;
  onChange: (poId: string) => void;
  /** The invoice's net amount as typed, checked against the order. */
  amountSubtotal: number;
  /** Set when editing, so the invoice is not counted against itself. */
  invoiceId?: string;
}) {
  const { t } = useTranslation();

  const { data: ordersPage, isLoading } = useQuery({
    queryKey: ['procurement-po', projectId, 'vendor', contactId],
    queryFn: () =>
      apiGet<Page<LinkableOrder>>(
        `/v1/procurement/?project_id=${encodeURIComponent(projectId)}&vendor_contact_id=${encodeURIComponent(contactId)}&limit=100`,
      ),
    enabled: !!projectId && !!contactId,
  });
  const orders = useMemo(
    () =>
      (ordersPage?.items ?? []).filter(
        (po) => !UNLINKABLE_STATUSES.has(po.status) || po.id === value,
      ),
    [ordersPage, value],
  );
  const selected = orders.find((po) => po.id === value);

  // Weigh the amount once typing settles, not on every keystroke.
  const [checkedAmount, setCheckedAmount] = useState(amountSubtotal);
  useEffect(() => {
    const handle = window.setTimeout(() => setCheckedAmount(amountSubtotal), 400);
    return () => window.clearTimeout(handle);
  }, [amountSubtotal]);

  const { data: check } = useQuery({
    queryKey: ['procurement-invoice-check', value, checkedAmount, invoiceId ?? ''],
    queryFn: () =>
      apiPost<InvoiceCheckResult>(`/v1/procurement/${value}/invoice-check/`, {
        amount_subtotal: String(checkedAmount),
        line_items: [],
        invoice_id: invoiceId || undefined,
      }),
    enabled: !!value && checkedAmount > 0,
  });
  const warnings = (check?.results ?? []).filter((r) => !r.passed);

  if (!contactId) {
    return (
      <p className="text-xs text-content-tertiary" data-testid="invoice-po-pick-supplier">
        {t('finance.po_link_pick_supplier', {
          defaultValue: 'Choose the supplier first to see its purchase orders.',
        })}
      </p>
    );
  }

  const ordered = Number(selected?.amount_subtotal ?? 0) || 0;
  const invoicedToDate = Number(selected?.invoiced_net ?? 0) || 0;
  const open = Math.max(0, ordered - invoicedToDate);

  return (
    <div className="space-y-2">
      <select
        className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={t('finance.po_link_label', { defaultValue: 'Purchase order' })}
        data-testid="invoice-po-select"
      >
        <option value="">{t('finance.po_link_none', { defaultValue: 'Not linked to an order' })}</option>
        {orders.map((po) => (
          <option key={po.id} value={po.id}>
            {po.po_number}
          </option>
        ))}
      </select>

      {!isLoading && orders.length === 0 && (
        <p className="text-xs text-content-tertiary" data-testid="invoice-po-no-orders">
          {t('finance.po_link_no_orders', {
            defaultValue: 'This supplier has no open purchase orders on this project.',
          })}
        </p>
      )}

      {selected && (
        <dl
          className="grid grid-cols-3 gap-2 rounded-lg border border-border-light bg-surface-secondary/50 px-3 py-2 text-xs"
          data-testid="invoice-po-figures"
        >
          <div>
            <dt className="text-content-tertiary">{t('finance.po_link_ordered', { defaultValue: 'Ordered' })}</dt>
            <dd className="tabular-nums font-medium text-content-primary">
              <MoneyDisplay amount={ordered} currency={selected.currency_code} />
            </dd>
          </div>
          <div>
            <dt className="text-content-tertiary">
              {t('finance.po_link_invoiced', { defaultValue: 'Invoiced to date' })}
            </dt>
            <dd className="tabular-nums font-medium text-content-primary">
              <MoneyDisplay amount={invoicedToDate} currency={selected.currency_code} />
            </dd>
          </div>
          <div>
            <dt className="text-content-tertiary">{t('finance.po_link_open', { defaultValue: 'Still open' })}</dt>
            <dd className="tabular-nums font-medium text-content-primary">
              <MoneyDisplay amount={open} currency={selected.currency_code} />
            </dd>
          </div>
          <p className="col-span-3 text-2xs text-content-tertiary">
            {t('finance.basis_net', { defaultValue: 'Net of VAT' })}
          </p>
        </dl>
      )}

      {selected && warnings.length > 0 && (
        <div
          className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-300"
          data-testid="invoice-po-warnings"
        >
          <ul className="space-y-1">
            {warnings.map((w) => (
              <li key={w.rule_id} className="flex items-start gap-1.5">
                <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                <span>{w.message}</span>
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-2xs opacity-80">
            {t('finance.po_link_warnings_note', {
              defaultValue: 'These are warnings only. The invoice can still be saved.',
            })}
          </p>
        </div>
      )}
    </div>
  );
}
