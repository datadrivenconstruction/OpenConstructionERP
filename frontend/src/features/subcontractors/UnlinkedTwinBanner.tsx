// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A subcontract that looks written twice, once as an agreement here and once
 * as a contract in Contracts, with nothing linking the two.
 *
 * Unlinked, finance counts such a pair as two commitments. Nothing in the data
 * proves they are one subcontract, so the page never merges them on its own:
 * it says what it found and lets a person link the pair (after a confirmation)
 * or say the two are different, which is remembered on the agreement.
 *
 * Shown on an agreement (``agreementId`` narrows it to that agreement's pairs)
 * and on the finance overview, where the double count shows up.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Link2 } from 'lucide-react';
import { Button, ConfirmDialog } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { dismissUnlinkedTwin, listUnlinkedTwins, updateAgreement, type UnlinkedTwin } from './api';

function contractLabel(pair: UnlinkedTwin): string {
  return [pair.contract_code, pair.contract_title].filter(Boolean).join(' ');
}

export function UnlinkedTwinBanner({
  projectId,
  agreementId,
}: {
  projectId: string;
  agreementId?: string;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [confirming, setConfirming] = useState<UnlinkedTwin | null>(null);

  const twinsQ = useQuery({
    queryKey: ['subcontractors', 'unlinked-twins', projectId],
    queryFn: () => listUnlinkedTwins(projectId),
    enabled: Boolean(projectId),
  });
  const pairs = (twinsQ.data ?? []).filter((p) => !agreementId || p.agreement_id === agreementId);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['subcontractors'] });
    qc.invalidateQueries({ queryKey: ['finance'] });
  };

  const link = useMutation({
    mutationFn: (pair: UnlinkedTwin) => updateAgreement(pair.agreement_id, { contract_id: pair.contract_id }),
    onSuccess: () => {
      setConfirming(null);
      refresh();
      addToast({ type: 'success', title: t('subcontractors.twin.linked') });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const dismiss = useMutation({
    mutationFn: (pair: UnlinkedTwin) => dismissUnlinkedTwin(pair.agreement_id, pair.contract_id),
    onSuccess: () => {
      refresh();
      addToast({ type: 'success', title: t('subcontractors.twin.dismissed') });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (pairs.length === 0) return null;

  return (
    <div className="space-y-2" data-testid="unlinked-twin-banner">
      {pairs.map((pair) => (
        <div
          key={`${pair.agreement_id}:${pair.contract_id}`}
          role="status"
          className="flex flex-col gap-2 rounded-lg border border-amber-200 bg-amber-50/70 px-3 py-2 text-sm dark:border-amber-800 dark:bg-amber-950/30 sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="flex min-w-0 items-start gap-2">
            <AlertTriangle size={15} className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" />
            <div className="min-w-0">
              <p className="text-content-primary">
                {t('subcontractors.twin.message', {
                  agreement: pair.agreement_title,
                  contract: contractLabel(pair),
                })}
              </p>
              {!pair.value_close && (
                <p className="mt-0.5 text-xs text-content-secondary">
                  {t('subcontractors.twin.values_differ')}{' '}
                  <MoneyDisplay amount={Number(pair.agreement_value)} currency={pair.currency} /> /{' '}
                  <MoneyDisplay amount={Number(pair.contract_value)} currency={pair.currency} />
                </p>
              )}
            </div>
          </div>
          <div className="flex shrink-0 gap-2">
            <Button
              size="sm"
              variant="secondary"
              icon={<Link2 size={13} />}
              onClick={() => setConfirming(pair)}
            >
              {t('subcontractors.twin.link')}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              loading={dismiss.isPending && dismiss.variables === pair}
              onClick={() => dismiss.mutate(pair)}
            >
              {t('subcontractors.twin.different')}
            </Button>
          </div>
        </div>
      ))}
      <ConfirmDialog
        open={confirming !== null}
        variant="warning"
        title={t('subcontractors.twin.confirm_title')}
        message={
          confirming
            ? t('subcontractors.twin.confirm_message', {
                agreement: confirming.agreement_title,
                contract: contractLabel(confirming),
              })
            : ''
        }
        confirmLabel={t('subcontractors.twin.link')}
        cancelLabel={t('common.cancel', { defaultValue: 'Cancel' })}
        loading={link.isPending}
        onConfirm={() => confirming && link.mutate(confirming)}
        onCancel={() => setConfirming(null)}
      />
    </div>
  );
}
