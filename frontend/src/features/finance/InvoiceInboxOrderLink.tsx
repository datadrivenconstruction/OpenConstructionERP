// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { apiGet, type Page } from '@/shared/lib/api';

interface Order {
  id: string;
  po_number: string;
  status: string;
  vendor_contact_id?: string | null;
  vendor_name?: string | null;
}

// The server refuses a link to an order in either of these states.
const UNLINKABLE = new Set(['draft', 'cancelled']);

/** Finding codes the server gives to order / goods-receipt mismatches awaiting acknowledgement. */
export const MATCH_CODE_PREFIX = 'po_match:';

export function hasOrderMismatch(validation: Array<{ code: string }> | undefined): boolean {
  return (validation ?? []).some((f) => f.code.startsWith(MATCH_CODE_PREFIX));
}

const SEARCH_DEBOUNCE_MS = 250;

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

/**
 * The order a captured invoice bills. The match against the order and its goods
 * receipts is computed by the server and arrives as validation findings, so this
 * only chooses the order. Orders are searched on the server by number or supplier,
 * so any order of the project is reachable however many there are.
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
  const [text, setText] = useState('');
  const [open, setOpen] = useState(false);
  const search = useDebounced(text.trim(), SEARCH_DEBOUNCE_MS);

  const { data, isFetching } = useQuery({
    queryKey: ['procurement-po', projectId, 'inbox-link', search],
    queryFn: () =>
      apiGet<Page<Order>>(
        `/v1/procurement/?project_id=${encodeURIComponent(projectId)}&limit=50&search=${encodeURIComponent(search)}`,
      ),
    enabled: !!projectId && open && !disabled,
  });
  const linked = useQuery({
    queryKey: ['procurement-po', projectId, 'inbox-link-selected', value],
    queryFn: () => apiGet<Order>(`/v1/procurement/${encodeURIComponent(value)}`),
    enabled: !!value,
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

  const selectedLabel = value ? (linked.data?.po_number ?? '') : '';
  const placeholder = t('finance.inbox.po_search', { defaultValue: 'Search by order number or supplier' });

  const pick = (poId: string) => {
    setOpen(false);
    setText('');
    onChange(poId);
  };

  return (
    <div className="relative space-y-1.5">
      <div className="flex items-center gap-2">
        <input
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-controls="inbox-po-listbox"
          aria-label={t('finance.inbox.po_label', { defaultValue: 'Purchase order' })}
          className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
          value={open ? text : selectedLabel}
          placeholder={value ? selectedLabel : t('finance.inbox.po_none', { defaultValue: 'Not linked to an order' })}
          disabled={disabled}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onChange={(e) => {
            setText(e.target.value);
            setOpen(true);
          }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setOpen(false);
          }}
          data-testid="inbox-po-select"
        />
        {value && !disabled && (
          <button
            type="button"
            className="shrink-0 rounded-lg border border-border px-3 py-2 text-sm text-content-secondary hover:bg-surface-secondary"
            onClick={() => pick('')}
            data-testid="inbox-po-clear"
          >
            {t('finance.inbox.po_none', { defaultValue: 'Not linked to an order' })}
          </button>
        )}
      </div>
      {open && !disabled && (
        <ul
          id="inbox-po-listbox"
          role="listbox"
          aria-label={placeholder}
          className="absolute z-20 max-h-60 w-full overflow-auto rounded-lg border border-border bg-surface-primary shadow-lg"
        >
          {orders.map((po) => (
            <li key={po.id} role="option" aria-selected={po.id === value}>
              <button
                type="button"
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-start text-sm hover:bg-surface-secondary"
                // mousedown fires before the input blurs, so the pick is not lost.
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(po.id)}
              >
                <span className="font-medium">{po.po_number}</span>
                {po.vendor_name && <span className="truncate text-xs text-content-tertiary">{po.vendor_name}</span>}
              </button>
            </li>
          ))}
          {!isFetching && orders.length === 0 && (
            <li className="px-3 py-2 text-xs text-content-tertiary" data-testid="inbox-po-no-orders">
              {search
                ? t('finance.inbox.po_no_match', { defaultValue: 'No matching purchase order.' })
                : t('finance.inbox.po_no_orders', { defaultValue: 'No open purchase orders on this project.' })}
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
