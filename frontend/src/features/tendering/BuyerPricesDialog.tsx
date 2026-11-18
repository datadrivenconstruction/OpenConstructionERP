// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Price a bid line by line on the buyer's side: for a quote that came by mail,
 * phone or on paper. The lines and quantities are the package's; the buyer
 * types the unit prices and the server sums the bid.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, SkeletonTable } from '@/shared/ui';
import { WideModal } from '@/shared/ui/WideModal';
import { formatCurrency } from '@/shared/lib/money';
import { fmtNumber } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { getPackagePreview, packagePreviewQueryKey, putBuyerPrices } from './api';

export interface BuyerPricesBid {
  id: string;
  company_name: string;
  currency: string;
  line_items: { position_id?: string; unit_rate?: number | string | null }[];
}

/** The unit price typed for a line, normalised to a decimal string, or null when blank or not a number. */
export function parsePrice(raw: string): string | null {
  const v = raw.trim().replace(/\s/g, '').replace(',', '.');
  if (!v) return null;
  return /^\d+(\.\d+)?$/.test(v) ? v : null;
}

/** Sum of price x quantity over the priced lines. */
export function pricedSum(prices: Record<string, string>, quantities: Record<string, string>): number {
  let sum = 0;
  for (const [id, raw] of Object.entries(prices)) {
    const p = parsePrice(raw);
    if (p == null) continue;
    sum += Number(p) * Number(quantities[id] || 0);
  }
  return sum;
}

export function BuyerPricesDialog({
  packageId,
  bid,
  onClose,
}: {
  packageId: string;
  bid: BuyerPricesBid;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [prices, setPrices] = useState<Record<string, string>>({});

  const previewQ = useQuery({
    queryKey: packagePreviewQueryKey(packageId),
    queryFn: () => getPackagePreview(packageId),
  });

  useEffect(() => {
    const initial: Record<string, string> = {};
    for (const item of bid.line_items ?? []) {
      if (item.position_id && item.unit_rate != null && item.unit_rate !== '') {
        initial[item.position_id] = String(item.unit_rate);
      }
    }
    setPrices(initial);
  }, [bid]);

  const items = useMemo(() => (previewQ.data?.lines ?? []).filter((l) => l.kind === 'item'), [previewQ.data]);
  const quantities = useMemo(() => Object.fromEntries(items.map((l) => [l.id, l.quantity])), [items]);
  const invalid = Object.values(prices).some((v) => v.trim() !== '' && parsePrice(v) == null);
  const priced = Object.values(prices).filter((v) => parsePrice(v) != null).length;
  const currency = previewQ.data?.currency || bid.currency;

  const mutation = useMutation({
    mutationFn: () => {
      const body: Record<string, string> = {};
      for (const [id, raw] of Object.entries(prices)) {
        const p = parsePrice(raw);
        if (p != null) body[id] = p;
      }
      return putBuyerPrices(bid.id, { unit_prices: body });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tendering-package', packageId] });
      queryClient.invalidateQueries({ queryKey: ['tendering-comparison', packageId] });
      queryClient.invalidateQueries({ queryKey: ['tendering-packages'] });
      addToast({ type: 'success', title: t('tendering.buyer_prices.saved', { defaultValue: 'Prices saved' }) });
      onClose();
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('tendering.buyer_prices.title', { defaultValue: 'Enter prices for {{company}}', company: bid.company_name })}
      size="xl"
      busy={mutation.isPending}
      footer={
        <>
          <span className="mr-auto text-sm tabular-nums text-content-secondary" data-testid="buyer-prices-total">
            {t('tendering.buyer_prices.total', {
              defaultValue: 'Priced: {{priced}} / {{lines}}, total {{total}}',
              priced,
              lines: items.length,
              total: formatCurrency(pricedSum(prices, quantities), currency),
            })}
          </span>
          <Button variant="ghost" onClick={onClose} disabled={mutation.isPending}>
            {t('common.cancel', 'Cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={invalid || priced === 0}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
            data-testid="buyer-prices-save"
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      {previewQ.isLoading ? (
        <SkeletonTable rows={5} columns={5} />
      ) : items.length === 0 ? (
        <p className="text-sm text-content-tertiary">
          {t('tendering.contents.no_lines', { defaultValue: 'This package has no lines to price yet.' })}
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border-light text-left text-xs text-content-tertiary">
              <th className="px-2 py-2">{t('tendering.contents.col_ordinal', { defaultValue: 'No.' })}</th>
              <th className="px-2 py-2">{t('tendering.contents.col_text', { defaultValue: 'Description' })}</th>
              <th className="px-2 py-2 text-right">{t('tendering.contents.col_qty', { defaultValue: 'Quantity' })}</th>
              <th className="px-2 py-2">{t('tendering.contents.col_unit', { defaultValue: 'Unit' })}</th>
              <th className="px-2 py-2 text-right">
                {t('tendering.buyer_prices.unit_price', { defaultValue: 'Unit price' })}
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((line) => {
              const raw = prices[line.id] ?? '';
              const bad = raw.trim() !== '' && parsePrice(raw) == null;
              return (
                <tr key={line.id} className="border-b border-border-light/60">
                  <td className="px-2 py-1.5 tabular-nums text-content-secondary">{line.ordinal}</td>
                  <td className="px-2 py-1.5">{line.short_text}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{fmtNumber(line.quantity)}</td>
                  <td className="px-2 py-1.5 text-content-secondary">{line.unit}</td>
                  <td className="px-2 py-1.5 text-right">
                    <input
                      type="text"
                      inputMode="decimal"
                      value={raw}
                      onChange={(e) => setPrices({ ...prices, [line.id]: e.target.value })}
                      aria-label={t('tendering.buyer_prices.unit_price_for', {
                        defaultValue: 'Unit price for {{line}}',
                        line: line.ordinal || line.short_text,
                      })}
                      aria-invalid={bad}
                      className={`oe-input oe-input-sm w-32 text-right tabular-nums ${bad ? 'border-semantic-error' : ''}`}
                      data-testid={`buyer-price-${line.id}`}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </WideModal>
  );
}
