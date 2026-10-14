// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One confirmation for every removal on the HSE frame: a register row, a link to another module's record
// or a role. Nothing is deleted before the person confirms.

import { useTranslation } from 'react-i18next';

import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';

import type { HseWrite } from './hooks';

export interface RemoveTarget {
  /** What is removed, in the reader's words: shown in the question. */
  name: string;
  run: () => Promise<unknown>;
}

interface Props {
  target: RemoveTarget | null;
  write: HseWrite;
  onClose: () => void;
}

export function RemoveConfirm({ target, write, onClose }: Props) {
  const { t } = useTranslation();
  return (
    <ConfirmDialog
      open={!!target}
      variant="danger"
      loading={write.pending}
      title={t('hseFrame.remove.title', { defaultValue: 'Remove this entry?' })}
      message={t('hseFrame.remove.body', {
        defaultValue: '{{name}} is removed from the HSE frame. The records of other modules stay where they are.',
        name: target?.name ?? '',
      })}
      confirmLabel={t('hseFrame.remove.confirm', { defaultValue: 'Remove' })}
      cancelLabel={t('common.cancel', { defaultValue: 'Cancel' })}
      onCancel={onClose}
      onConfirm={() => {
        const run = target?.run;
        onClose();
        if (run) write.send(run);
      }}
    />
  );
}
