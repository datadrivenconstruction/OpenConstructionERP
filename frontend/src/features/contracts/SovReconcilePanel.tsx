// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Change orders and variations approved before they reached the schedule of
// values. They moved the contract sum and no line, so the claims had nothing
// to bill the change against. The server lists them with the amount each
// would add; a person reads the list and confirms it, and the apply posts
// exactly that list or nothing (409 when it changed in the meantime).
//
// Renders nothing when there is nothing to reconcile, which is every contract
// whose changes were approved after the poster existed.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ListPlus } from 'lucide-react';

import { Button } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { fmtDate } from '@/shared/lib/formatters';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { applySovReconcile, getSovReconcilePreview } from './api';

export function SovReconcilePanel({ contractId }: { contractId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [confirming, setConfirming] = useState(false);

  const previewQ = useQuery({
    queryKey: ['contracts', 'sov-reconcile', contractId],
    queryFn: () => getSovReconcilePreview(contractId),
  });
  const preview = previewQ.data;

  const applyMut = useMutation({
    mutationFn: () =>
      applySovReconcile(
        contractId,
        (preview?.items ?? []).map((item) => item.source_key),
      ),
    onSuccess: (result) => {
      setConfirming(false);
      addToast({
        type: 'success',
        title: t('contracts.sov_reconcile_done', {
          defaultValue: 'Lines added to the schedule of values: {{lines}}',
          lines: result.posted ?? 0,
        }),
      });
      qc.invalidateQueries({ queryKey: ['contracts', 'sov-reconcile', contractId] });
      qc.invalidateQueries({ queryKey: ['contracts', 'lines', contractId] });
      qc.invalidateQueries({ queryKey: ['contracts', 'sov-status', contractId] });
    },
    onError: (err) => {
      setConfirming(false);
      addToast({ type: 'error', title: getErrorMessage(err) });
      // A stale preview is the usual cause: show the list as it is now.
      qc.invalidateQueries({ queryKey: ['contracts', 'sov-reconcile', contractId] });
    },
  });

  if (!preview || preview.items.length === 0) return null;
  const currency = preview.currency || undefined;

  return (
    <div className="mt-3 rounded-lg border border-border-light bg-semantic-warning-bg p-3 text-sm">
      <p className="font-medium text-content-primary">
        {t('contracts.sov_reconcile_title', {
          defaultValue: 'Approved changes missing from the schedule of values',
        })}
      </p>
      <p className="mt-1 text-content-secondary">
        {t('contracts.sov_reconcile_hint', {
          defaultValue:
            'These changes moved the contract sum before change orders added lines to the schedule of values, so no claim can bill them yet.',
        })}
      </p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-content-tertiary">
            <tr>
              <th className="py-1 text-start">
                {t('contracts.code', { defaultValue: 'Code' })}
              </th>
              <th className="py-1 text-start">
                {t('contracts.description', { defaultValue: 'Description' })}
              </th>
              <th className="py-1 text-start">
                {t('contracts.sov_reconcile_approved_on', { defaultValue: 'Approved' })}
              </th>
              <th className="py-1 text-end">
                {t('contracts.total', { defaultValue: 'Total' })}
              </th>
            </tr>
          </thead>
          <tbody>
            {preview.items.map((item) => (
              <tr key={item.source_key} className="border-t border-border-light">
                <td className="py-1 font-mono">{item.source_code}</td>
                <td className="py-1">{item.title}</td>
                <td className="py-1">{item.approved_on ? fmtDate(item.approved_on) : '—'}</td>
                <td className="py-1 text-end">
                  <MoneyDisplay amount={item.amount} currency={item.currency || currency} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-content-secondary">
        {t('contracts.sov', { defaultValue: 'Schedule of Values' })}:{' '}
        <MoneyDisplay amount={preview.scheduled_total} currency={currency} /> →{' '}
        <MoneyDisplay amount={preview.scheduled_total_after} currency={currency} /> ·{' '}
        {t('contracts.sov_reconcile_contract_sum', { defaultValue: 'Contract sum to date' })}:{' '}
        <MoneyDisplay amount={preview.contract_sum} currency={currency} />
      </p>
      {!preview.can_apply ? (
        <p className="mt-2 text-content-tertiary">
          {t('contracts.sov_reconcile_active_only', {
            defaultValue: 'Changes are added to the schedule of values of an active contract only.',
          })}
        </p>
      ) : confirming ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="text-content-primary">
            {t('contracts.sov_reconcile_confirm', {
              defaultValue: 'Add each listed change to the schedule of values as a line of its own?',
            })}
          </span>
          <Button size="sm" onClick={() => applyMut.mutate()} loading={applyMut.isPending}>
            {t('common.confirm', { defaultValue: 'Confirm' })}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setConfirming(false)}
            disabled={applyMut.isPending}
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
        </div>
      ) : (
        <Button size="sm" variant="secondary" className="mt-2" onClick={() => setConfirming(true)}>
          <ListPlus size={13} className="me-1" aria-hidden />
          {t('contracts.sov_reconcile_action', { defaultValue: 'Reconcile change orders' })}
        </Button>
      )}
    </div>
  );
}
