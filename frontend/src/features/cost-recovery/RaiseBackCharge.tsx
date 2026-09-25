// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Charge this back" panel for a punch item or an NCR.
 *
 * Picks the subcontractor responsible (or leaves a free-text party) and
 * records a back-charge linked to the source, which fills the amount and the
 * description on the server. Once a subcontractor is chosen it also shows what
 * that subcontractor already owes back on the project, so a second charge for
 * the same defect is visible before it is raised.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { formatCurrency } from '@/shared/lib/money';
import { useToastStore } from '@/stores/useToastStore';
import { listSubcontractors } from '@/features/subcontractors/api';
import {
  createSourceBackCharge,
  getPendingBackCharges,
  sourceBackChargeBody,
  type BackChargeSource,
} from './api';

const FIELD_CLS =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30';

export function RaiseBackCharge({
  projectId,
  source,
  disabled,
}: {
  projectId: string;
  source: BackChargeSource;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [subcontractorId, setSubcontractorId] = useState('');
  const [party, setParty] = useState('');

  const { data: subs } = useQuery({
    queryKey: ['cost-recovery', 'subcontractor-options'],
    queryFn: () => listSubcontractors({ limit: 200, active_only: true }),
    enabled: open,
  });
  const { data: pending } = useQuery({
    queryKey: ['cost-recovery', 'pending', projectId, subcontractorId],
    queryFn: () => getPendingBackCharges(projectId, subcontractorId),
    enabled: open && !!subcontractorId,
  });

  const mutation = useMutation({
    mutationFn: () => createSourceBackCharge(projectId, sourceBackChargeBody(source, subcontractorId, party)),
    onSuccess: (bc) => {
      setOpen(false);
      setSubcontractorId('');
      setParty('');
      void queryClient.invalidateQueries({ queryKey: ['change-intelligence'] });
      void queryClient.invalidateQueries({ queryKey: ['cost-recovery', 'pending', projectId] });
      addToast({
        type: 'success',
        title: t('cost_recovery.raise.created', {
          defaultValue: 'Back-charge of {{amount}} recorded against {{party}}',
          amount: formatCurrency(bc.gross_amount, bc.currency),
          party: bc.responsible_party || t('cost_recovery.raise.unassigned', { defaultValue: 'no party yet' }),
        }),
      });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('cost_recovery.raise.failed', { defaultValue: 'Could not record the back-charge' }),
        message: getErrorMessage(err),
      }),
  });

  if (!open) {
    return (
      <Button size="sm" variant="secondary" disabled={disabled} onClick={() => setOpen(true)}>
        {t('cost_recovery.raise.open', { defaultValue: 'Charge back' })}
      </Button>
    );
  }

  const pendingTotals = Object.entries(pending?.totals ?? {});

  return (
    <div className="space-y-2 rounded-lg border border-border-light p-3" data-testid="raise-back-charge">
      <label className="block text-xs font-medium text-content-secondary">
        {t('cost_recovery.raise.subcontractor', { defaultValue: 'Subcontractor responsible' })}
        <select
          className={FIELD_CLS + ' mt-1'}
          value={subcontractorId}
          onChange={(e) => setSubcontractorId(e.target.value)}
        >
          <option value="">{t('cost_recovery.raise.no_subcontractor', { defaultValue: 'Not a listed subcontractor' })}</option>
          {(subs?.items ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.trade_name ? `${s.legal_name} (${s.trade_name})` : s.legal_name}
            </option>
          ))}
        </select>
      </label>
      {!subcontractorId && (
        <label className="block text-xs font-medium text-content-secondary">
          {t('cost_recovery.raise.party', { defaultValue: 'Responsible party' })}
          <input
            className={FIELD_CLS + ' mt-1'}
            value={party}
            onChange={(e) => setParty(e.target.value)}
            placeholder={t('cost_recovery.raise.party_ph', { defaultValue: 'Supplier, designer or other party' })}
          />
        </label>
      )}
      {pendingTotals.length > 0 && (
        <p className="text-xs text-content-secondary">
          {t('cost_recovery.raise.already_pending', {
            defaultValue: 'Already agreed and not yet deducted on this project: {{amounts}}',
            amounts: pendingTotals.map(([cur, amount]) => formatCurrency(amount, cur)).join(', '),
          })}
        </p>
      )}
      <p className="text-xs text-content-tertiary">
        {t('cost_recovery.raise.hint', {
          defaultValue: 'The amount and description come from this record. Agree the charge in the recovery ledger.',
        })}
      </p>
      <div className="flex gap-2">
        <Button size="sm" variant="primary" loading={mutation.isPending} onClick={() => mutation.mutate()}>
          {t('cost_recovery.raise.submit', { defaultValue: 'Record back-charge' })}
        </Button>
        <Button size="sm" variant="ghost" disabled={mutation.isPending} onClick={() => setOpen(false)}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
      </div>
    </div>
  );
}
