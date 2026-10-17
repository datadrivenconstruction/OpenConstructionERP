// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Asked when a row is put on a cost line other than the one it inherits from
// the bill or its contract line. The reason stays on the row with who and
// when, so the next person sees why it departs from the chain.
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/shared/ui';
import { WideModal } from '@/shared/ui/WideModal';

/** The server asks for at least this many characters. */
export const MIN_REASON_LENGTH = 3;

export interface OverrideReasonDialogProps {
  open: boolean;
  busy?: boolean;
  onCancel: () => void;
  onConfirm: (reason: string) => void;
}

export function OverrideReasonDialog({ open, busy = false, onCancel, onConfirm }: OverrideReasonDialogProps) {
  const { t } = useTranslation();
  const [reason, setReason] = useState('');
  useEffect(() => {
    if (open) setReason('');
  }, [open]);
  const clean = reason.trim();
  const ok = clean.length >= MIN_REASON_LENGTH;

  return (
    <WideModal
      open={open}
      onClose={onCancel}
      busy={busy}
      size="md"
      title={t('costmodel.override.title', { defaultValue: 'Why does it go on this cost line?' })}
      subtitle={t('costmodel.override.subtitle', {
        defaultValue:
          'It takes another cost line from the bill or its contract line. Say why it belongs here; the reason is kept with your name and the date.',
      })}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => onConfirm(clean)}
            disabled={busy || !ok}
            data-testid="override-reason-confirm"
          >
            {t('costmodel.override.confirm', { defaultValue: 'Put it there' })}
          </Button>
        </div>
      }
    >
      <label className="block text-sm">
        <span className="text-content-secondary">{t('costmodel.override.reason', { defaultValue: 'Reason' })}</span>
        <textarea
          className="mt-1 w-full rounded-lg border border-border bg-surface-primary px-3 py-2"
          rows={3}
          value={reason}
          maxLength={2000}
          onChange={(e) => setReason(e.target.value)}
          placeholder={t('costmodel.override.placeholder', {
            defaultValue: 'e.g. Agreed with the client to carry this as contingency',
          })}
          data-testid="override-reason-input"
        />
      </label>
    </WideModal>
  );
}
