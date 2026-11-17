// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** "Extract actions" for meeting minutes: proposed action items, owners limited to project contacts. */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { WideModal } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  confirmProposal,
  extractMeetingActions,
  rejectProposal,
  type MeetingActionItem,
  type MeetingActionsEnvelope,
} from './api';
import { ProposalReview } from './ProposalReview';

interface Props {
  open: boolean;
  onClose: () => void;
  meetingId: string;
  onSaved: () => void;
}

const inputCls =
  'w-full rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary';

export function MeetingActionsDialog({ open, onClose, meetingId, onSaved }: Props) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [data, setData] = useState<MeetingActionsEnvelope | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const run = useMutation({
    mutationFn: () => extractMeetingActions(meetingId),
    onSuccess: setData,
  });
  const save = useMutation({
    mutationFn: (sel: Parameters<typeof confirmProposal>[1]) => confirmProposal(data!.proposal_id!, sel),
    onSuccess: (res) => {
      const bad = res.results.filter((r) => r.status === 'error');
      if (bad.length) {
        setErrors(
          Object.fromEntries(
            bad.map((r) => [
              r.id,
              typeof r.detail === 'string' ? r.detail : t('site_ai.actions.needs_owner_due', { defaultValue: 'An action needs an owner and a due date.' }),
            ]),
          ),
        );
        return;
      }
      addToast({
        type: 'success',
        title: t('site_ai.actions.saved', { defaultValue: 'Action items added: {{n}}', n: res.results.length }),
      });
      onSaved();
      close();
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('site_ai.save_failed', { defaultValue: 'Could not save' }), message: e.message }),
  });

  const close = () => {
    setData(null);
    setErrors({});
    onClose();
  };

  useEffect(() => {
    if (open) {
      setData(null);
      run.mutate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, meetingId]);

  const runError = run.error as (Error & { message: string }) | null;

  return (
    <WideModal
      open={open}
      onClose={close}
      size="lg"
      busy={save.isPending}
      title={t('site_ai.actions.title', { defaultValue: 'Action items from the minutes' })}
      subtitle={t('site_ai.actions.subtitle', {
        defaultValue: 'Accept the ones that are real. Owners come from the project contacts. Nothing is added until you confirm.',
      })}
      testId="meeting-actions-dialog"
    >
      {run.isPending && (
        <p className="flex items-center gap-2 text-sm text-content-tertiary">
          <Loader2 size={14} className="animate-spin" />
          {t('site_ai.actions.reading', { defaultValue: 'Reading the minutes...' })}
        </p>
      )}
      {runError && (
        <p role="alert" className="text-sm text-semantic-error" data-testid="meeting-actions-error">
          {runError.message}
        </p>
      )}
      {data && (
        <ProposalReview<MeetingActionItem>
          items={data.items}
          degraded={data.degraded}
          errors={errors}
          busy={save.isPending}
          onRejectAll={() => {
            void rejectProposal(data.proposal_id!).finally(close);
          }}
          onConfirm={(sel) => save.mutate(sel)}
          emptyLabel={t('site_ai.actions.none', { defaultValue: 'No action items found in the minutes.' })}
          renderItem={(i) => (
            <div className="flex flex-col gap-0.5">
              <span className="font-medium">{i.text}</span>
              <span className="text-xs text-content-tertiary">
                {i.owner_name ?? t('site_ai.actions.no_owner', { defaultValue: 'No owner' })}
                {' · '}
                {i.due ?? t('site_ai.actions.no_due', { defaultValue: 'No due date' })}
              </span>
            </div>
          )}
          renderEdit={(i, _d, set) => (
            <div className="grid gap-2 sm:grid-cols-2">
              <input
                className={`${inputCls} sm:col-span-2`}
                aria-label={t('site_ai.actions.text', { defaultValue: 'Action' })}
                defaultValue={i.text}
                onChange={(e) => set({ text: e.target.value })}
              />
              <select
                className={inputCls}
                aria-label={t('site_ai.actions.owner', { defaultValue: 'Owner' })}
                defaultValue={i.owner_name ?? ''}
                onChange={(e) => set({ owner_name: e.target.value || null, owner_id: null })}
              >
                <option value="">{t('site_ai.actions.no_owner', { defaultValue: 'No owner' })}</option>
                {data.allowed_owners.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
              <input
                className={inputCls}
                type="date"
                aria-label={t('site_ai.actions.due', { defaultValue: 'Due date' })}
                defaultValue={i.due ?? ''}
                onChange={(e) => set({ due: e.target.value || null })}
              />
            </div>
          )}
        />
      )}
    </WideModal>
  );
}
