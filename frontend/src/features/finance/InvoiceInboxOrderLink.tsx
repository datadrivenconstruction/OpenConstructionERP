// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { apiGet, type Page } from '@/shared/lib/api';

interface Order {
  id: string;
  po_number: string;
  status: string;
  vendor_contact_id?: string | null;
}

// The server refuses a link to an order in either of these states.
const UNLINKABLE = new Set(['draft', 'cancelled']);

/** Finding codes the server gives to order / goods-receipt mismatches awaiting acknowledgement. */
export const MATCH_CODE_PREFIX = 'po_match:';

export function hasOrderMismatch(validation: Array<{ code: string }> | undefined): boolean {
  return (validation ?? []).some((f) => f.code.startsWith(MATCH_CODE_PREFIX));
}

/**
 * The order a captured invoice bills. The match against the order and its goods
 * receipts is computed by the server and arrives as validation findings, so this
 * only chooses the order.
 */
export function InvoiceInboxOrderLink({
  projectId,
  supplierContactId,
  value,
  disabled,
  onChange,
}: {
  projectId: string;
  supplierContactId: string | null;
  value: string;
  disabled: boolean;
  onChange: (poId: string) => void;
}) {
  const { t } = useTranslation();
  const { data, isLoading } = useQuery({
    queryKey: ['procurement-po', projectId, 'inbox-link'],
    queryFn: () => apiGet<Page<Order>>(`/v1/procurement/?project_id=${encodeURIComponent(projectId)}&limit=100`),
    enabled: !!projectId,
  });
  const orders = useMemo(
    () =>
      (data?.items ?? []).filter(
        (po) =>
          po.id === value ||
          (!UNLINKABLE.has(po.status) &&
            (!supplierContactId || !po.vendor_contact_id || po.vendor_contact_id === supplierContactId)),
      ),
    [data, value, supplierContactId],
  );

  return (
    <div className="space-y-1.5">
      <select
        className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        aria-label={t('finance.inbox.po_label', { defaultValue: 'Purchase order' })}
        data-testid="inbox-po-select"
      >
        <option value="">{t('finance.inbox.po_none', { defaultValue: 'Not linked to an order' })}</option>
        {orders.map((po) => (
          <option key={po.id} value={po.id}>
            {po.po_number}
          </option>
        ))}
      </select>
      {!isLoading && orders.length === 0 && (
        <p className="text-xs text-content-tertiary" data-testid="inbox-po-no-orders">
          {t('finance.inbox.po_no_orders', { defaultValue: 'No open purchase orders on this project.' })}
        </p>
      )}
    </div>
  );
}
