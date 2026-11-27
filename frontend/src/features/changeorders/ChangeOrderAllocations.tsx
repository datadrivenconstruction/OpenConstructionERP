// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { apiPatch } from '@/shared/lib/api';
import { isDecimalString, subtractDecimalStrings, sumDecimalStrings } from '@/shared/lib/exactDecimal';

export interface CommitmentAllocation {
  kind: 'purchase_order' | 'subcontract';
  id: string;
  amount: string;
}

/**
 * The share of a change order each linked purchase order carries.
 *
 * A change order linked to one order raises that order by its whole amount. One
 * linked to several raises none of them until it is split here: only the share
 * entered for an order raises that order's limit, and the shares must add up to
 * the change order amount.
 */
export function ChangeOrderAllocations({
  orderId,
  poIds,
  allocations,
  amount,
  currency,
  canEdit,
}: {
  orderId: string;
  poIds: string[];
  allocations: CommitmentAllocation[];
  amount: string;
  currency: string;
  canEdit: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const stored = (id: string) => allocations.find((a) => a.kind === 'purchase_order' && a.id === id)?.amount ?? '';
  const [shares, setShares] = useState<Record<string, string>>(() =>
    Object.fromEntries(poIds.map((id) => [id, stored(id)])),
  );
  const storedKey = JSON.stringify(allocations);
  useEffect(() => {
    setShares(Object.fromEntries(poIds.map((id) => [id, stored(id)])));
    // Reload when the saved allocations or the links change, not on each keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storedKey, poIds.join(',')]);

  const entered = poIds.map((id) => (shares[id] ?? '').trim());
  const valid = entered.every((v) => v === '' || isDecimalString(v));
  const total = valid ? (sumDecimalStrings(entered.filter(Boolean)) ?? '0') : null;
  const gap = total != null && isDecimalString(amount) ? subtractDecimalStrings(amount, total) : null;
  const balanced = gap != null && Number(gap) === 0;
  const unallocated = allocations.length === 0;

  const save = useMutation({
    mutationFn: () =>
      apiPatch(`/v1/changeorders/${orderId}`, {
        commitment_allocations: poIds
          .filter((id) => (shares[id] ?? '').trim() !== '')
          .map((id) => ({ kind: 'purchase_order', id, amount: (shares[id] ?? '').trim() })),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['changeorder', orderId] });
    },
  });

  if (poIds.length < 2) return null;
  return (
    <div className="mb-6 space-y-2" data-testid="co-allocations">
      <h3 className="oe-section-title">
        {t('changeorders.allocations_title', { defaultValue: 'Split across orders' })}
      </h3>
      {unallocated && (
        <p className="text-xs text-semantic-warning" data-testid="co-allocations-missing">
          {t('changeorders.allocations_missing', {
            defaultValue: 'Allocate this change order: until it is split, it raises none of the linked orders.',
          })}
        </p>
      )}
      <table className="oe-table oe-table-compact text-xs">
        <tbody>
          {poIds.map((id, i) => (
            <tr key={id}>
              <td title={id}>{t('changeorders.linked_po', { defaultValue: 'PO {{n}}', n: i + 1 })}</td>
              <td className="w-36">
                <input
                  className="oe-input w-full tabular-nums text-right"
                  inputMode="decimal"
                  value={shares[id] ?? ''}
                  disabled={!canEdit}
                  aria-label={t('changeorders.linked_po', { defaultValue: 'PO {{n}}', n: i + 1 })}
                  data-testid={`co-allocation-${id}`}
                  onChange={(e) => setShares((prev) => ({ ...prev, [id]: e.target.value }))}
                />
              </td>
            </tr>
          ))}
          <tr>
            <td>{t('changeorders.allocations_total', { defaultValue: 'Allocated' })}</td>
            <td
              className={`text-right tabular-nums ${balanced ? '' : 'text-semantic-error'}`}
              data-testid="co-allocations-total"
            >
              <MoneyDisplay amount={total} currency={currency} />
              {' / '}
              <MoneyDisplay amount={isDecimalString(amount) ? amount : null} currency={currency} />
            </td>
          </tr>
        </tbody>
      </table>
      {canEdit && (
        <Button
          size="sm"
          variant="secondary"
          disabled={!balanced || save.isPending}
          onClick={() => save.mutate()}
          data-testid="co-allocations-save"
        >
          {t('changeorders.allocations_save', { defaultValue: 'Save split' })}
        </Button>
      )}
      {save.isError && (
        <p className="text-xs text-semantic-error" role="alert">
          {(save.error as Error).message}
        </p>
      )}
    </div>
  );
}
