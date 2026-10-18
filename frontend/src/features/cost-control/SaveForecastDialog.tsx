// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Start a snapshot of today's forecast. It opens as a draft: the reasons behind
// large moves are written on it, then it is frozen for good. The stage is
// optional context: leave it on "Forecast" for the monthly report, pick
// "Award" or "Final account" when the snapshot marks one of those milestones. Each stage shows its national names, so a
// German, British or American user recognises their own step.
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/shared/ui';
import { WideModal } from '@/shared/ui/WideModal';
import { COST_STAGES, type CostStage, type SnapshotCreate } from './api';
import { stageHint, stageLabel } from './labels';

export interface SaveForecastDialogProps {
  open: boolean;
  busy: boolean;
  onClose: () => void;
  onSave: (body: SnapshotCreate) => void;
}

export function SaveForecastDialog({ open, busy, onClose, onSave }: SaveForecastDialogProps) {
  const { t } = useTranslation();
  const [stage, setStage] = useState<CostStage>('forecast');
  const [label, setLabel] = useState('');
  const [note, setNote] = useState('');

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={busy}
      size="md"
      title={t('cost_control.draft_start_title', { defaultValue: "Start this month's snapshot" })}
      subtitle={t('cost_control.draft_start_subtitle', {
        defaultValue:
          "Takes today's figures into a draft. Write the reason behind each large move, then freeze it: a frozen snapshot is never changed.",
      })}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={() => onSave({ stage, label, note })} disabled={busy}>
            {t('cost_control.draft_start_confirm', { defaultValue: 'Start draft' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <fieldset>
          <legend className="mb-2 text-sm font-medium text-content-primary">
            {t('cost_control.save_stage', { defaultValue: 'What does this forecast mark?' })}
          </legend>
          <div className="space-y-1.5">
            {COST_STAGES.map((s) => (
              <label
                key={s}
                className={`flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2 ${
                  stage === s ? 'border-oe-blue bg-oe-blue-subtle/40' : 'border-border-light'
                }`}
              >
                <input
                  type="radio"
                  name="cost-stage"
                  className="mt-1"
                  checked={stage === s}
                  onChange={() => setStage(s)}
                />
                <span>
                  <span className="block text-sm text-content-primary">{stageLabel(t, s)}</span>
                  <span className="block text-xs text-content-tertiary">{stageHint(t, s)}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <label className="block text-sm">
          <span className="text-content-secondary">{t('cost_control.save_label', { defaultValue: 'Title (optional)' })}</span>
          <input
            className="mt-1 h-9 w-full rounded-lg border border-border bg-surface-primary px-3"
            value={label}
            maxLength={200}
            onChange={(e) => setLabel(e.target.value)}
            placeholder={t('cost_control.save_label_placeholder', { defaultValue: 'e.g. Cost report October' })}
          />
        </label>
        <label className="block text-sm">
          <span className="text-content-secondary">{t('cost_control.save_note', { defaultValue: 'Note (optional)' })}</span>
          <textarea
            className="mt-1 w-full rounded-lg border border-border bg-surface-primary px-3 py-2"
            rows={3}
            value={note}
            maxLength={4000}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
      </div>
    </WideModal>
  );
}
