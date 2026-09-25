// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';

/**
 * How much of a purchase order has been invoiced so far, against its value.
 *
 * Both figures are net of VAT: `invoiced` is the server's `invoiced_net`
 * (payable invoices linked to the order, drafts and cancelled ones left out)
 * and `ordered` is the order's `amount_subtotal`. Comparing the gross order
 * total with net invoices would show every order as under-invoiced by the
 * VAT rate.
 */
export function OrderInvoicedSummary({
  invoiced,
  ordered,
  currency,
  className,
}: {
  invoiced: string | number | null | undefined;
  ordered: string | number | null | undefined;
  currency?: string;
  className?: string;
}) {
  const { t } = useTranslation();
  const invoicedN = Number(invoiced ?? 0) || 0;
  const orderedN = Number(ordered ?? 0) || 0;
  const over = orderedN > 0 && invoicedN > orderedN + 0.005;
  const pct = orderedN > 0 ? Math.min(100, Math.max(0, (invoicedN / orderedN) * 100)) : 0;

  return (
    <div
      className={clsx('text-2xs text-content-tertiary', className)}
      title={t('procurement.po_invoiced_tooltip', {
        defaultValue: 'Net invoiced against this order so far, out of its net value.',
      })}
      data-testid="po-invoiced-summary"
    >
      <div className="flex items-center justify-end gap-1 whitespace-nowrap">
        <span>{t('procurement.po_invoiced_label', { defaultValue: 'Invoiced (net)' })}</span>
        <span className={clsx('tabular-nums', over && 'font-medium text-amber-600 dark:text-amber-400')}>
          <MoneyDisplay amount={invoicedN} currency={currency} />
        </span>
        <span>/</span>
        <span className="tabular-nums">
          <MoneyDisplay amount={orderedN} currency={currency} />
        </span>
      </div>
      <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-surface-secondary">
        <div
          className={clsx('h-full rounded-full', over ? 'bg-amber-500' : 'bg-oe-blue')}
          style={{ width: `${over ? 100 : pct}%` }}
        />
      </div>
      {over && (
        <div className="mt-0.5 text-amber-600 dark:text-amber-400">
          {t('procurement.po_invoiced_over', { defaultValue: 'Invoiced above the order value' })}
        </div>
      )}
    </div>
  );
}
